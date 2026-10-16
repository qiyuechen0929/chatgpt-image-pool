"""窗口池预热（新池必跑一次）—— 让插件长连接与目标站首访状态就绪

两个必须预热的理由
------------------
1. **插件配置是存在窗口 profile 里的**（chrome.storage.local）。全新窗口第一次启动时，
   Chromium 冷启动 + 扩展 service worker 初始化可能超过任务等待时间，
   任务会直接失败：`浏览器插件未连接：space_id='default' window_key='N'`。
2. 全新 profile **从未访问过 chatgpt.com**，首次访问的 Cookie / cf_clearance 还没建立，
   插件在页面上下文 fetch 会拿到空结果：
   `GPT pageFetch returned empty result for /backend-api/f/conversation`。

预热一次后配置持久化，之后窗口每次启动都会自动重连。

用法：
    python scripts/warmup_windows.py                    # 预热任务池里全部窗口
    python scripts/warmup_windows.py --keys 6,16        # 只补某几个
    python scripts/warmup_windows.py --space-pk 5 --task-type-id 6
    python scripts/warmup_windows.py --visit ""         # 不访问目标站，只连插件
    python scripts/warmup_windows.py --keep-open        # 预热后不关窗口
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def pool_windows(p: C.Paths, space_pk: int, task_type_id: int) -> list[dict]:
    conn = C.sqlite_connect(p.fpb_db)
    try:
        rows = conn.execute(
            """
            SELECT w.window_key, w.window_name, w.platform_account
            FROM task_type_windows tc JOIN windows w ON w.id = tc.window_pk
            WHERE tc.task_type_id = ? AND tc.deleted = 0 AND w.deleted = 0 AND tc.enabled = 1
            ORDER BY w.id
            """,
            (task_type_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def bridge_config(p: C.Paths) -> tuple[str, str, str]:
    """返回 (bridge_ws_url, token, launcher_base)。"""
    cfg = C.read_setting_toml(p)
    ext = (cfg.get("extension_executor") or {}) if cfg else {}
    base = str(ext.get("base_url") or "").strip()
    token = str(ext.get("bridge_token") or "").strip()
    if base:
        bridge = f"ws://{base}/api/extension/ws"
        launcher = f"http://{base}/"
    else:
        bridge = f"ws://127.0.0.1:{p.fpb_port}/api/extension/ws"
        launcher = f"http://127.0.0.1:{p.fpb_port}/"
    env_bridge = (C.os.environ.get("FPB_EXTENSION_BRIDGE_URL") or "").strip()
    if env_bridge:
        bridge = env_bridge
    return bridge, token, launcher


def build_launcher(launcher_base: str, window_key: str, bridge: str, token: str, space_id: str, redirect: str) -> str:
    frag = {
        "fpb_space_id": space_id,
        "fpb_window_key": str(window_key),
        "fpb_bridge_url": bridge,
        "redirect_url": redirect,
    }
    if token:
        frag["fpb_bridge_token"] = token
    return f"{launcher_base.rstrip('/')}/#{urlencode(frag)}"


def clients(p: C.Paths) -> list[dict]:
    try:
        return C.http_json(f"{p.fpb_api_url}/api/extension/clients", timeout=8).get("clients") or []
    except Exception:
        return []


def running_ids(p: C.Paths) -> set[str]:
    try:
        rows = C.http_json(f"{p.vb_api_url}/api/getBrowserRunningList", timeout=8).get("data") or []
        return {str(r.get("id")) for r in rows}
    except Exception:
        return set()


async def warm_one(p: C.Paths, window_key: str, launcher: str, wait_seconds: float, visit: str) -> tuple[bool, str]:
    wid = int(window_key) if str(window_key).isdigit() else window_key
    rsp = C.http_json(f"{p.vb_api_url}/api/launchBrowser", {"id": wid}, timeout=120)
    if rsp.get("success") is False:
        msg = str(rsp.get("msg") or "")
        if "异常退出" in msg or str(window_key) in running_ids(p):
            C.info("      (窗口可能已开着，先关闭再重试)")
            C.http_json(f"{p.vb_api_url}/api/stopBrowser", {"id": wid}, timeout=60)
            await asyncio.sleep(2.5)
            rsp = C.http_json(f"{p.vb_api_url}/api/launchBrowser", {"id": wid}, timeout=120)
            if rsp.get("success") is False:
                return False, f"启动失败(已重试)：{rsp.get('msg')}"
        else:
            return False, f"启动失败：{msg}"

    port = (rsp.get("data") or {}).get("debuggingPort") or (rsp.get("data") or {}).get("port")
    if not port:
        return False, "未取到 CDP 调试端口"

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await page.goto(launcher, wait_until="domcontentloaded", timeout=40000)
            except Exception as e:
                # 插件自己可能已经把页面跳走了，导致 goto 被中断（ERR_ABORTED），不算失败
                if "ERR_ABORTED" not in repr(e):
                    return False, f"打开中转页失败：{e!r}"
            await browser.close()
    except Exception as e:
        return False, f"CDP 连接失败：{e!r}"

    deadline = time.time() + max(5.0, wait_seconds)
    registered = False
    while time.time() < deadline:
        if any(str(c.get("window_key")) == str(window_key) for c in clients(p)):
            registered = True
            break
        await asyncio.sleep(2)
    if not registered:
        return False, "等待插件注册超时"

    if visit:
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                try:
                    await page.goto(visit, wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(6)
                    title = await page.title()
                except Exception as e:
                    title = f"(访问被中断 {str(e)[:40]})"
                await browser.close()
            return True, f"已注册 + 已访问目标站 {title[:22]}"
        except Exception as e:
            return True, f"已注册（访问目标站失败：{e!r}）"
    return True, "已注册"


async def main_async(args: argparse.Namespace) -> int:
    p = C.Paths.discover()
    if not C.tcp_listening(p.vb_port) or not C.tcp_listening(p.fpb_port):
        C.fail("服务未就绪 → python scripts/start_all.py")
        return 1

    conn = C.sqlite_connect(p.fpb_db)
    try:
        auto_space, auto_tt = C.detect_pool_ids(conn)
    finally:
        conn.close()
    space_pk = args.space_pk or auto_space
    task_type_id = args.task_type_id or auto_tt

    rows = pool_windows(p, space_pk, task_type_id)
    if args.keys:
        want = {k.strip() for k in args.keys.split(",") if k.strip()}
        rows = [r for r in rows if str(r["window_key"]) in want]
    if not rows:
        C.warn("没有需要预热的窗口（窗口池为空？先跑 import_chatgpt_tokens.py / sync_vb_pool.py）")
        return 1

    bridge, token, launcher_base = bridge_config(p)
    C.title(f"窗口池预热（{len(rows)} 个窗口）")
    C.log(f"  bridge    : {bridge}")
    C.log(f"  launcher  : {launcher_base}")
    C.log("  space_id  : default")
    C.log("")

    ok = fail = 0
    failed: list[str] = []
    for i, r in enumerate(rows, 1):
        key = str(r["window_key"])
        launcher = build_launcher(launcher_base, key, bridge, token, "default", args.visit or "https://chatgpt.com/")
        t0 = time.time()
        good, msg = await warm_one(p, key, launcher, args.wait, args.visit)
        C.log(f"  [{i:2d}/{len(rows)}] win={key:<4} {str(r['window_name'])[:20]:<22} {time.time() - t0:5.1f}s  {'OK  ' if good else 'FAIL'} {msg}")
        if good:
            ok += 1
        else:
            fail += 1
            failed.append(key)
        if not args.keep_open:
            C.http_json(f"{p.vb_api_url}/api/stopBrowser", {"id": int(key) if key.isdigit() else key}, timeout=60)
            await asyncio.sleep(1.2)

    C.log("")
    C.log("-" * 68)
    C.ok(f"预热完成：成功 {ok}，失败 {fail}")
    if failed:
        C.info(f"失败窗口：{failed}（再跑一次本脚本即可重试）")
    C.info("提示：之后窗口启动会自动重连插件，任务无需再等中转页。")
    return 0 if fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="窗口池预热")
    ap.add_argument("--space-pk", type=int, default=0)
    ap.add_argument("--task-type-id", type=int, default=0)
    ap.add_argument("--keys", default="", help="只预热这些 window_key，逗号分隔")
    ap.add_argument("--wait", type=float, default=60.0, help="每个窗口等待插件注册的上限秒数")
    ap.add_argument("--visit", default="https://chatgpt.com/", help="预热时顺便访问的目标站（空字符串=不访问）")
    ap.add_argument("--keep-open", action="store_true", help="预热后不关闭窗口")
    args = ap.parse_args()
    C.ensure_stdout_encoding()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
