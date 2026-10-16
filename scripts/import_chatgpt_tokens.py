"""卡密导入：`邮箱----密码----2FA密钥----access_token` → 直接建成 ChatGPT 号池

为什么推荐这条路
----------------
卡密里的第 4 段是 ChatGPT 长 access_token。本项目的 `gpt_workflow` 会**优先使用
窗口池里缓存的 token**（`task_type_windows.sora_access_token`），只有在它缺失/过期时
才回落到浏览器会话。所以带 token 的卡密**不需要跑浏览器登录**，
也就绕过了 Cloudflare、邮箱验证码、2FA 这些最容易失败的环节。

脚本做四件事（都是幂等的，可重复执行）
------------------------------------
1. 逐个校验 token（直连 `https://chatgpt.com/backend-api/me`）
2. VirtualBrowser 建/复用指纹环境（名字 `ChatGPT-Worker-NN`，备注=邮箱）
3. 同步窗口到 FPBrowser2API 空间 + 清理失效窗口
4. 写 `platform_accounts`（邮箱/密码/2FA）、窗口↔账号绑定、任务池绑定 + 长 token

用法
----
    # 先导 1 个验证链路
    python scripts/import_chatgpt_tokens.py -f accounts.txt --only 1

    # 确认能出图后全量导入
    python scripts/import_chatgpt_tokens.py -f accounts.txt --yes

    # 环境已存在（例如只换了一批新卡密），只更新账号与 token
    python scripts/import_chatgpt_tokens.py -f accounts.txt --no-create-envs --yes

    # 每个窗口用不同代理：把代理列表按顺序对应卡密顺序
    python scripts/import_chatgpt_tokens.py -f accounts.txt --proxy-file proxies.txt --yes

格式说明：分隔符支持 `----`（四连字符）与 `——`（中文长横线）；
多余的 `# 注释` 行、空行、表头行会被自动忽略。
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

CHATGPT_URL = "https://chatgpt.com/"


# --------------------------------------------------------------------------
# 卡密解析
# --------------------------------------------------------------------------
class Account:
    def __init__(self, email: str, password: str, efa: str, token: str):
        self.email = email.strip()
        self.password = password.strip()
        self.efa = efa.strip()
        self.token = token.strip()

    @property
    def jwt(self) -> dict:
        try:
            part = self.token.split(".")[1]
            part += "=" * (-len(part) % 4)
            return json.loads(base64.urlsafe_b64decode(part.encode("ascii")).decode("utf-8", "replace"))
        except Exception:
            return {}

    @property
    def exp_ts(self) -> int:
        return int(self.jwt.get("exp") or 0)

    @property
    def exp_local(self) -> str:
        return datetime.fromtimestamp(self.exp_ts).strftime("%Y-%m-%d %H:%M:%S") if self.exp_ts else ""

    @property
    def plan(self) -> str:
        auth = self.jwt.get("https://api.openai.com/v1/auth") or self.jwt.get("https://api.openai.com/auth") or {}
        return str(auth.get("chatgpt_plan_type") or "")

    @property
    def account_id(self) -> str:
        auth = self.jwt.get("https://api.openai.com/v1/auth") or self.jwt.get("https://api.openai.com/auth") or {}
        return str(auth.get("chatgpt_account_id") or "")


def parse_accounts(path: Path) -> list[Account]:
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        raise SystemExit(f"无法识别文件编码：{path}")

    out: list[Account] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "----" not in line and "——" not in line:
            continue
        parts = [p.strip() for p in (line.split("----") if "----" in line else line.split("——"))]
        if len(parts) < 3 or "@" not in parts[0]:
            continue
        acc = Account(parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "", parts[3] if len(parts) > 3 else "")
        if acc.email.lower() in seen:
            continue
        seen.add(acc.email.lower())
        out.append(acc)
    return out


def verify_token(acc: Account, timeout: float = 20.0) -> tuple[bool, str]:
    if not acc.token:
        return False, "卡密里没有 access_token（这种卡密请改用 batch_bind_chatgpt.py 登录）"
    headers = {
        "Authorization": f"Bearer {acc.token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "OAI-Language": "zh-CN",
        "OAI-Client-Version": "prod-81e0c5cdf6140e8c5db714d613337f4aeab94029",
        "OAI-Client-Build-Number": "6128297",
        "OAI-Device-Id": "00000000-0000-4000-8000-000000000000",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
    }
    req = urllib.request.Request("https://chatgpt.com/backend-api/me", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
            return True, f"{d.get('email')} / {d.get('name')}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, repr(e)[:70]


# --------------------------------------------------------------------------
# VirtualBrowser
# --------------------------------------------------------------------------
class VirtualBrowser:
    def __init__(self, base_url: str, default_proxy: str = ""):
        self.base = base_url.rstrip("/")
        self.default_proxy = default_proxy

    def list_browsers(self) -> list[dict]:
        for payload in ({}, None):
            try:
                return C.http_json(f"{self.base}/api/getBrowserList", payload, timeout=30).get("data") or []
            except Exception:
                continue
        return []

    def proxy_payload(self, proxy: str) -> dict:
        host = port = ""
        if proxy and ":" in proxy:
            host, port = proxy.split(":", 1)
        return {
            "mode": 1 if host and port else 0,
            "value": f"{host}:{port}" if host and port else "",
            "protocol": "HTTP",
            "host": host,
            "port": port,
            "user": "",
            "pass": "",
            "API": "",
        }

    def ensure_env(self, name: str, email: str, proxy: str) -> int:
        for b in self.list_browsers():
            if str(b.get("remark") or "").strip().lower() == email.lower() or str(b.get("name") or "") == name:
                wid = int(b["id"])
                patch: dict = {"id": wid, "name": name, "remark": email}
                if proxy:
                    patch["proxy"] = self.proxy_payload(proxy)
                try:
                    C.http_json(f"{self.base}/api/updateBrowser", patch, timeout=30)
                except Exception as e:
                    C.warn(f"更新环境 {wid} 失败（忽略）：{e}")
                return wid
        payload = {
            "name": name,
            "group": ["默认分组"],
            "homepage": {"mode": 1, "value": CHATGPT_URL},
            "remark": email,
            "proxy": self.proxy_payload(proxy),
        }
        rsp = C.http_json(f"{self.base}/api/addBrowser", payload, timeout=60)
        if not rsp.get("success"):
            raise RuntimeError(f"创建环境失败：{rsp.get('msg')}")
        return int(rsp["data"]["id"])


# --------------------------------------------------------------------------
# 写库
# --------------------------------------------------------------------------
def write_db(p: C.Paths, *, space_pk: int, task_type_id: int, bindings: list[dict], quota: int) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = C.sqlite_connect(p.fpb_db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for b in bindings:
            acc: Account = b["account"]
            window_pk = int(b["window_pk"])

            row = conn.execute(
                "SELECT account_id FROM platform_accounts WHERE space_pk = ? AND platform_username = ? AND deleted = 0",
                (space_pk, acc.email),
            ).fetchone()
            raw = json.dumps(
                {
                    "email": acc.email,
                    "password": acc.password,
                    "efa": acc.efa,
                    "chatgpt_account_id": acc.account_id,
                    "plan": acc.plan,
                    "token_expires": acc.exp_local,
                },
                ensure_ascii=False,
            )
            if row:
                account_id = int(row["account_id"])
                conn.execute(
                    """UPDATE platform_accounts
                       SET platform_url=?, platform_password=?, platform_efa=?, raw_json=?,
                           deleted=0, synced_at=?, updated_at=?
                       WHERE space_pk=? AND account_id=?""",
                    (CHATGPT_URL, acc.password, acc.efa, raw, ts, ts, space_pk, account_id),
                )
            else:
                nid = conn.execute(
                    "SELECT COALESCE(MAX(account_id), 0) + 1 AS nid FROM platform_accounts WHERE space_pk = ?",
                    (space_pk,),
                ).fetchone()["nid"]
                account_id = int(nid)
                conn.execute(
                    """INSERT INTO platform_accounts
                       (space_pk, account_id, platform_url, platform_username, platform_password,
                        platform_efa, platform_remarks, deleted, raw_json, synced_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
                    (space_pk, account_id, CHATGPT_URL, acc.email, acc.password, acc.efa,
                     f"卡密导入 {ts}", raw, ts, ts, ts),
                )

            conn.execute(
                """UPDATE windows
                   SET platform_account=?, platform_url=?, platform_account_id=?, window_remark=?, updated_at=?
                   WHERE id=?""",
                (acc.email, CHATGPT_URL, account_id, acc.email, ts, window_pk),
            )

            tw = conn.execute(
                "SELECT id FROM task_type_windows WHERE task_type_id = ? AND window_pk = ?",
                (task_type_id, window_pk),
            ).fetchone()
            if tw:
                conn.execute(
                    """UPDATE task_type_windows
                       SET enabled=1, deleted=0, remaining_quota=?, sora_access_token=?, sora_access_expires=?,
                           error_cooldown_until=NULL, cooldown_until=NULL, consecutive_errors=0, updated_at=?
                       WHERE id=?""",
                    (quota, acc.token, acc.exp_local, ts, int(tw["id"])),
                )
            else:
                conn.execute(
                    """INSERT INTO task_type_windows
                       (task_type_id, window_pk, enabled, remaining_quota, sora_access_token,
                        sora_access_expires, deleted, created_at, updated_at)
                       VALUES (?, ?, 1, ?, ?, ?, 0, ?, ?)""",
                    (task_type_id, window_pk, quota, acc.token, acc.exp_local, ts, ts),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="ChatGPT 卡密导入号池（长 token 直灌）")
    ap.add_argument("-f", "--file", required=True, help="卡密文件")
    ap.add_argument("--prefix", default="ChatGPT-Worker", help="环境名前缀")
    ap.add_argument("--start-index", type=int, default=1)
    ap.add_argument("--only", type=int, default=0, help="只导前 N 个（0=全部）")
    ap.add_argument("--space-pk", type=int, default=0)
    ap.add_argument("--task-type-id", type=int, default=0)
    ap.add_argument("--proxy", default="", help="统一代理 host:port")
    ap.add_argument("--proxy-file", default="", help="代理列表文件（按行对应卡密顺序）")
    ap.add_argument("--remaining-quota", type=int, default=999)
    ap.add_argument("--no-create-envs", action="store_true", help="不新建环境，只按备注(邮箱)匹配已有环境")
    ap.add_argument("--skip-verify", action="store_true", help="跳过 token 联网校验")
    ap.add_argument("--yes", action="store_true", help="不询问，直接写库")
    ap.add_argument("--dry-run", action="store_true", help="只解析与校验，不写任何数据")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    p = C.Paths.discover()
    C.title("ChatGPT 卡密导入号池")

    accounts = parse_accounts(Path(args.file))
    if args.only > 0:
        accounts = accounts[: args.only]
    if not accounts:
        C.fail("未解析到任何账号。格式应为：邮箱----密码----2FA密钥----access_token")
        return 1

    proxies: list[str] = []
    if args.proxy_file and Path(args.proxy_file).exists():
        proxies = [ln.strip() for ln in Path(args.proxy_file).read_text(encoding="utf-8", errors="replace").splitlines()
                   if ln.strip() and not ln.strip().startswith("#")]

    C.info(f"账号数：{len(accounts)}    空间：{args.space_pk or '自动'}    任务类型：{args.task_type_id or '自动'}")
    if proxies:
        C.info(f"代理：按顺序为每个窗口分配（共 {len(proxies)} 个）")

    if not C.tcp_listening(p.vb_port) or not C.tcp_listening(p.fpb_port):
        C.fail("服务未就绪 → python scripts/start_all.py")
        return 1

    # 1) token 校验
    if not args.skip_verify:
        C.log("")
        C.info("[1/5] 校验 token（直连 ChatGPT 接口）...")
        good = 0
        for acc in accounts:
            okk, detail = verify_token(acc)
            C.log(f"      [{'OK  ' if okk else 'FAIL'}] {acc.email:<38} plan={acc.plan:<6} 到期 {acc.exp_local}  {detail}")
            good += 1 if okk else 0
        if good == 0:
            C.fail("没有可用 token，终止（检查卡密是否过期或网络是否可达 chatgpt.com）")
            return 1
        if good < len(accounts):
            C.warn(f"{len(accounts) - good} 个 token 校验失败，仍会写入但大概率不可用")

    # 2) 环境
    vb = VirtualBrowser(p.vb_api_url, default_proxy=args.proxy)
    env_map: dict[str, int] = {}
    C.log("")
    if args.no_create_envs:
        C.info("[2/5] 按备注(邮箱)匹配已有环境 ...")
        by_remark = {str(b.get("remark") or "").strip().lower(): int(b["id"]) for b in vb.list_browsers()}
        for acc in accounts:
            wid = by_remark.get(acc.email.lower())
            if wid:
                env_map[acc.email] = wid
            else:
                C.warn(f"找不到邮箱 {acc.email} 对应的环境，跳过")
    else:
        C.info("[2/5] 准备 VirtualBrowser 环境 ...")
        for i, acc in enumerate(accounts, start=args.start_index):
            name = f"{args.prefix}-{i:02d}"
            proxy = args.proxy or (proxies[(i - args.start_index) % len(proxies)] if proxies else "")
            wid = vb.ensure_env(name=name, email=acc.email, proxy=proxy)
            env_map[acc.email] = wid
            C.log(f"      {name:<24} 环境ID={wid:<4} {acc.email:<38} 代理={proxy or '直连'}")

    if not env_map:
        C.fail("没有任何可用环境，终止")
        return 1

    # 3) 同步窗口
    C.log("")
    C.info("[3/5] 同步窗口 ...")
    login = C.http_json(f"{p.fpb_api_url}/api/admin/login", {"username": "admin", "password": "admin"}, timeout=20)
    token = login.get("token") or ""
    conn = C.sqlite_connect(p.fpb_db)
    try:
        auto_space, auto_tt = C.detect_pool_ids(conn)
    finally:
        conn.close()
    space_pk = args.space_pk or auto_space
    task_type_id = args.task_type_id or auto_tt
    if not space_pk or not task_type_id:
        C.fail("无法自动识别空间/任务类型，请用 --space-pk / --task-type-id 指定")
        return 1

    remote_keys = {str(b.get("id")) for b in vb.list_browsers()}
    for w in C.http_json(f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/windows", token=token, timeout=30).get("windows") or []:
        if str(w.get("window_key")) not in remote_keys:
            try:
                C.http_json(
                    f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/windows/{w.get('window_key')}/delete",
                    {"delete_remote": False, "delete_account": False}, token=token, timeout=30,
                )
            except Exception:
                pass
    sync = C.http_json(f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/sync-windows", {}, token=token, timeout=180)
    C.info(f"      {sync.get('message')}")

    windows = C.http_json(f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/windows", token=token, timeout=30).get("windows") or []
    key_to_pk = {str(w.get("window_key")): int(w["id"]) for w in windows}

    bindings = []
    for acc in accounts:
        wid = env_map.get(acc.email)
        if wid is None:
            continue
        pk = key_to_pk.get(str(wid))
        if pk is None:
            C.warn(f"FPBrowser2API 中找不到 window_key={wid}（{acc.email}），跳过")
            continue
        bindings.append({"account": acc, "window_pk": pk, "window_key": str(wid)})

    if not bindings:
        C.fail("没有可绑定的窗口，终止")
        return 1

    # 4) 写库
    C.log("")
    C.info(f"[4/5] 写入账号 / 窗口绑定 / 任务池 token（{len(bindings)} 条）")
    C.info(f"      数据库：{p.fpb_db}")
    if args.dry_run:
        C.info("      dry-run：不写库，结束")
        return 0
    if not args.yes:
        if input("      确认写入？(y/N) ").strip().lower() != "y":
            C.info("      已取消")
            return 1
    backup = p.fpb_db.with_suffix(f".bak-{time.strftime('%Y%m%d-%H%M%S')}.db")
    shutil.copy2(p.fpb_db, backup)
    C.info(f"      已备份 → {backup.name}")
    write_db(p, space_pk=space_pk, task_type_id=task_type_id, bindings=bindings, quota=args.remaining_quota)
    C.ok("      写入完成")

    # 5) 复核
    C.log("")
    C.info("[5/5] 复核 ...")
    conn = C.sqlite_connect(p.fpb_db)
    try:
        rows = conn.execute(
            """
            SELECT w.window_key, w.window_name, w.platform_account, tc.enabled, tc.sora_access_expires,
                   CASE WHEN COALESCE(tc.sora_access_token,'') = '' THEN '无' ELSE '有' END AS tok
            FROM task_type_windows tc JOIN windows w ON w.id = tc.window_pk
            WHERE tc.task_type_id = ? AND tc.deleted = 0 AND w.deleted = 0 ORDER BY w.id
            """,
            (task_type_id,),
        ).fetchall()
        C.ok(f"      任务类型 {task_type_id} 窗口池共 {len(rows)} 条")
        for r in rows[:30]:
            C.log(f"        win={str(r['window_key']):<4}{str(r['window_name'])[:22]:<24}"
                  f"{str(r['platform_account'] or '-')[:32]:<34}启用={'是' if r['enabled'] else '否'} "
                  f"token={r['tok']}({r['sora_access_expires'] or '-'})")
    finally:
        conn.close()

    C.log("")
    C.ok("导入完成。下一步：")
    C.info("  1) python scripts/warmup_windows.py            （新池首次必须预热）")
    C.info("  2) python scripts/gen_image.py \"一只柴犬宇航员\" -o out.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
