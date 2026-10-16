"""一行出图：走号池调度 → 轮询 → 自动取回原图（含鉴权下载）

为什么需要它：ChatGPT 生成图的下载地址是内部 estuary 链接，
直接下载会 403（`File stream access denied`）。本脚本会自动用
**跑这个任务的那个窗口的长 token** 去下载，并校验确实是图片。

用法
----
    python scripts/gen_image.py "一只柴犬宇航员" -o out/shiba.png
    python scripts/gen_image.py "雨夜霓虹街道的机械武士" --style cyberpunk --ratio 16:9 -o out/a.png
    python scripts/gen_image.py "产品图：银色机械键盘" --res 2k --ratio 1:1 -o out/kb.png
    python scripts/gen_image.py "原样提交不要扩写" --raw-prompt -o out/raw.png
    python scripts/gen_image.py "批量任务用 --json 取机器可读输出" --json

退出码：0 成功 / 2 提交失败 / 3 任务失败 / 4 下载失败 / 5 参数或环境问题
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

IMAGE_MAGIC_OK = (b"\x89PNG", b"\xff\xd8", b"GIF8", b"RIFF", b"BM")
EXIT_OK, EXIT_SUBMIT, EXIT_TASK, EXIT_DOWNLOAD, EXIT_ENV = 0, 2, 3, 4, 5


class PoolError(RuntimeError):
    """带退出码的号池错误（比用字符串匹配判断错误类型可靠）。"""

    def __init__(self, message: str, exit_code: int = EXIT_TASK) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class SubmitError(PoolError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_SUBMIT)


class DownloadError(PoolError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_DOWNLOAD)


# 「报错现象 → 下一步该做什么」映射（新手看得懂的建议，而不是只丢一句错）
KNOWN_ERRORS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("插件未连接", "extension not connected", "not connected"), "插件长连接没建立 → 跑 pool.bat warm（新池必做一次）"),
    (("pageFetch", "empty result"), "目标站首访状态没就绪 → 跑 pool.bat warm 让窗口先访问一次 chatgpt.com"),
    (("access token", "token 过期", "unauthorized", "401"), "窗口 token 失效 → 重新导入卡密：pool.bat import accounts.txt --yes"),
    (("quota", "额度", "insufficient", "balance"), "账号额度用尽 → 换号或补号：pool.bat import accounts.txt --yes"),
    (("window pool", "没有可用窗口", "no window"), "窗口池为空 → 先导入卡密并绑定：pool.bat import accounts.txt --yes"),
    (("cooldown", "冷却"), "窗口在错误冷却中 → 等几分钟，或 pool.bat status 看解冻时间"),
    (("Connection refused", "连接被拒", "10061"), "服务没启动 → pool.bat start"),
    (("File stream access denied", "403"), "结果图下载需窗口 token → 本脚本已自动处理；仍失败就直接重跑一次"),
)


def diagnose(err: str) -> str:
    """把错误信息翻译成「下一步该做什么」。"""
    s = str(err or "")
    for keys, advice in KNOWN_ERRORS:
        if any(k.lower() in s.lower() for k in keys):
            return advice
    return ""

# 模型「只回文字不画图 / 反问澄清」的特征词（免费号常见）。
# 命中后自动用更强的指令重试，而不是直接把失败抛给用户。
_CLARIFY_HINTS = (
    "已生成",
    "生成好了",
    "你更喜欢",
    "要更贴合",
    "请确认",
    "你想要",
    "希望我",
    "可以告诉我",
    "让我知道",
)


def is_clarify_failure(err: str) -> bool:
    s = str(err or "")
    return any(h in s for h in _CLARIFY_HINTS)


def harden_prompt(prompt: str) -> str:
    """针对「反问/只回文字」的加固提示词。"""
    return (
        "直接调用画图工具生成图片，不要输出任何解释、确认、选项或提问，"
        "不要反问用户偏好，现在就画。画面要求：" + str(prompt).strip()
    )


# --------------------------------------------------------------------------
# 基础能力
# --------------------------------------------------------------------------
def resolve_api_key(p: C.Paths, explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    env = (C.os.environ.get("FPB_API_KEY") or "").strip()
    if env:
        return env
    try:
        conn = C.sqlite_connect(p.fpb_db)
        row = conn.execute("SELECT api_key FROM system_config WHERE id = 1").fetchone()
        conn.close()
        if row and row["api_key"]:
            return str(row["api_key"])
    except Exception:
        pass
    return "fpb123456"


def optimize_prompt(p: C.Paths, prompt: str, style: str, ratio: str, res: str, raw: bool) -> str:
    """可选：复用上游 skill 的提示词扩写器（防 ChatGPT 反问）。缺失时原样返回。"""
    if raw:
        return prompt
    script_dir = None
    if p.fpb_root:
        cand = p.fpb_root / "skills" / "chatgpt-image-gen" / "scripts"
        if (cand / "prompt_optimizer.py").exists():
            script_dir = cand
    if script_dir is None:
        return prompt
    try:
        sys.path.insert(0, str(script_dir))
        from prompt_optimizer import optimize_prompt as _opt  # type: ignore

        try:
            out = _opt(prompt, style=style, ratio=ratio, resolution=res)
        except TypeError:
            out = _opt(prompt)
        return str(out or prompt)
    except Exception:
        return prompt


def looks_like_image(data: bytes) -> bool:
    return len(data) > 5000 and any(data.startswith(m) for m in IMAGE_MAGIC_OK)


def token_for_task(p: C.Paths, task_id: str) -> str:
    """取跑该任务的窗口绑定的长 token（用于 estuary 授权下载）。"""
    try:
        conn = C.sqlite_connect(p.fpb_db)
        row = conn.execute(
            """
            SELECT tc.sora_access_token AS tok
            FROM tasks t
            JOIN task_type_windows tc ON tc.window_pk = t.window_pk AND tc.deleted = 0
            WHERE t.task_id = ? AND COALESCE(tc.sora_access_token, '') <> ''
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        conn.close()
        return str(row["tok"] or "") if row else ""
    except Exception:
        return ""


def download_image(p: C.Paths, image_url: str, out_path: Path, task_id: str = "", auth_token: str = "") -> int:
    """优先用窗口 token 下载；失败再试匿名；均失败抛错。返回字节数。"""
    attempts: list[tuple[str, dict]] = []
    tok = auth_token or (token_for_task(p, task_id) if task_id else "")
    if tok:
        attempts.append(
            (
                "窗口 token",
                {
                    "Authorization": f"Bearer {tok}",
                    "User-Agent": "Mozilla/5.0",
                    "Origin": "https://chatgpt.com",
                    "Referer": "https://chatgpt.com/",
                },
            )
        )
    attempts.append(("匿名", {"User-Agent": "Mozilla/5.0"}))

    last_err = ""
    for label, headers in attempts:
        try:
            req = urllib.request.Request(image_url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if looks_like_image(data):
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(data)
                return len(data)
            last_err = f"{label} 返回非图片内容：{data[:80]!r}"
        except urllib.error.HTTPError as e:
            last_err = f"{label} HTTP {e.code}"
        except Exception as e:
            last_err = f"{label} {e!r}"
    raise DownloadError(f"图片下载失败（{last_err}）")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def submit_and_wait(
    *,
    p: C.Paths,
    api_url: str,
    api_key: str,
    prompt: str,
    ratio: str,
    res: str,
    timeout: float,
    poll: float,
    quiet: bool = False,
) -> dict:
    model = f"gpt-image2-{res}"
    # 注意：图片模型经 /v1/videos 提交时，服务端会把 seconds 自动置为 4；
    # 如果偏偏传了 duration/seconds，则必须等于 4（详见 docs/05-daily-use.md）。
    payload = {"model": model, "prompt": prompt, "aspect_ratio": ratio}
    rsp = C.http_json(f"{api_url}/v1/videos", payload, token=api_key, timeout=60)
    task_id = rsp.get("id") or rsp.get("task_id")
    if not task_id:
        raise SubmitError(f"提交失败，返回内容异常：{json.dumps(rsp, ensure_ascii=False)[:300]}")
    if not quiet:
        C.info(f"已入队：{task_id}（model={model} ratio={ratio}）")

    t0 = time.time()
    last_state = None
    while time.time() - t0 < timeout:
        time.sleep(poll)
        st = C.http_json(f"{api_url}/v1/videos/{task_id}", token=api_key, timeout=60)
        status = st.get("status") or st.get("state")
        if not quiet and status != last_state:
            C.info(f"[{int(time.time() - t0):4d}s] 状态：{status} 进度：{st.get('progress')}")
            last_state = status
        if st.get("final") or status in ("completed", "failed", "succeeded"):
            st["_task_id"] = task_id
            return st
    raise TimeoutError(f"任务超时（>{timeout:.0f}s），任务号 {task_id}（可稍后用 GET /v1/videos/{task_id} 查询）")


def first_image_url(result: dict) -> str:
    if result.get("image_url"):
        return str(result["image_url"])
    if result.get("url"):
        return str(result["url"])
    urls = ((result.get("metadata") or {}).get("result_urls")) or []
    if urls:
        return str(urls[0])
    return ""


def generate_one(
    *,
    p: C.Paths,
    api_url: str,
    api_key: str,
    prompt: str,
    out_path: Path,
    ratio: str = "1:1",
    res: str = "1k",
    style: str = "concept_art",
    raw_prompt: bool = False,
    timeout: float = 900.0,
    poll: float = 5.0,
    quiet: bool = False,
    retries: int = 2,
) -> dict:
    """完整跑一条：扩写 → 提交 → 等待 → 下载（对「只回文字不画图」自动重试）。"""
    final_prompt = optimize_prompt(p, prompt, style, ratio, res, raw_prompt)
    if not quiet and final_prompt != prompt:
        C.info(f"提示词已扩写（{len(prompt)} → {len(final_prompt)} 字），如需原样提交加 --raw-prompt")

    last: dict = {}
    for attempt in range(max(0, retries) + 1):
        use_prompt = final_prompt if attempt == 0 else harden_prompt(final_prompt)
        if attempt > 0 and not quiet:
            C.info(f"模型上一轮只回了文字（反问/未画图），用加固提示词重试 {attempt}/{retries} ...")

        result = submit_and_wait(
            p=p, api_url=api_url, api_key=api_key, prompt=use_prompt,
            ratio=ratio, res=res, timeout=timeout, poll=poll, quiet=quiet,
        )
        status = result.get("status") or result.get("state")
        task_id = result.get("_task_id") or ""
        if status == "completed":
            url = first_image_url(result)
            if not url:
                last = {"ok": False, "task_id": task_id, "status": status, "error": "任务完成但结果里没有图片地址"}
                break
            size = download_image(p, url, out_path, task_id=task_id)
            return {
                "ok": True, "task_id": task_id, "status": status, "image_url": url,
                "saved_path": str(out_path.resolve()), "bytes": size, "attempts": attempt + 1,
            }

        err = (result.get("error") or {}).get("message") or result.get("error_message") or "未知错误"
        last = {"ok": False, "task_id": task_id, "status": status, "error": str(err), "attempts": attempt + 1}
        # 只有「模型反问/只回文字」才重试；真错（额度、未登录等）立即返回
        if not is_clarify_failure(str(err)):
            break
    return last


def main() -> int:
    ap = argparse.ArgumentParser(description="一行出图（走 ChatGPT 号池）")
    ap.add_argument("prompt", nargs="?", default="", help="提示词（含标点时建议用 --prompt-file）")
    ap.add_argument("--prompt-file", default="", help="从文件读提示词（避免命令行引号/特殊字符问题）")
    ap.add_argument("-o", "--output", default="", help="输出图片路径（默认 ./output/<时间戳>.png）")
    ap.add_argument("-r", "--ratio", default="1:1", help="画幅：1:1 / 16:9 / 9:16 / 4:3 / 3:4")
    ap.add_argument("--res", default="1k", choices=["1k", "2k", "4k"], help="分辨率层级")
    ap.add_argument("-s", "--style", default="concept_art", help="风格（配合提示词扩写）")
    ap.add_argument("--raw-prompt", action="store_true", help="不扩写，原样提交")
    ap.add_argument("--api-key", default="", help="FPBrowser2API 公开 API Key（默认从数据库读）")
    ap.add_argument("--fpb-url", default="", help="FPBrowser2API 地址（默认自动探测）")
    ap.add_argument("--timeout", type=float, default=900.0, help="等待任务完成的上限秒数")
    ap.add_argument("--poll", type=float, default=5.0, help="轮询间隔秒数")
    ap.add_argument("--quiet", action="store_true", help="少打印")
    ap.add_argument("--retries", type=int, default=2, help="模型只回文字不画图时的重试次数（默认 2）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果（便于程序调用）")
    args = ap.parse_args()

    # 提示词来源：--prompt-file 优先（标题、逗号、括号、& | ^ 等符号在 cmd 里很容易被吃掉）
    prompt = args.prompt
    if args.prompt_file:
        pf = Path(args.prompt_file)
        if not pf.exists():
            print(f"[FAIL] 提示词文件不存在：{pf}")
            return EXIT_ENV
        raw = pf.read_bytes()
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                prompt = raw.decode(enc).strip()
                break
            except Exception:
                continue
    if not prompt:
        print('[FAIL] 缺少提示词：pool.bat gen "一只柴犬" -o out.png  或  --prompt-file prompt.txt')
        return EXIT_ENV
    args.prompt = prompt

    C.ensure_stdout_encoding()
    p = C.Paths.discover()
    api_url = args.fpb_url.rstrip("/") if args.fpb_url else p.fpb_api_url

    out = Path(args.output) if args.output else Path.cwd() / "output" / f"img_{time.strftime('%Y%m%d-%H%M%S')}.png"

    if not args.json:
        C.title("号池出图")
        C.log(f"  调度服务：{api_url}")
        C.log(f"  输出路径：{out}")

    if not C.tcp_listening(p.fpb_port) and "127.0.0.1" in api_url:
        msg = f"FPBrowser2API 未在 {p.fpb_port} 端口监听 → 先执行 pool.bat start"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        else:
            C.fail(msg)
        return EXIT_ENV

    try:
        result = generate_one(
            p=p, api_url=api_url, api_key=resolve_api_key(p, args.api_key),
            prompt=args.prompt, out_path=out, ratio=args.ratio, res=args.res, style=args.style,
            raw_prompt=args.raw_prompt, timeout=args.timeout, poll=args.poll,
            quiet=args.quiet or args.json, retries=args.retries,
        )
    except Exception as e:
        msg = str(e)
        code = getattr(e, "exit_code", None) or (EXIT_SUBMIT if "401" in msg else EXIT_TASK)
        hint = diagnose(msg)
        if args.json:
            print(json.dumps({"ok": False, "error": msg, "hint": hint}, ensure_ascii=False))
        else:
            C.fail(msg)
            if hint:
                C.info(f"建议：{hint}")
        return code

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif result["ok"]:
        C.ok(f"出图成功：{result['saved_path']}（{result['bytes'] / 1024:.0f} KB）")
        C.info(f"任务号：{result['task_id']}")
    else:
        C.fail(f"任务失败：{result.get('error')}")
        C.info(f"任务号：{result.get('task_id')}")
        hint = diagnose(str(result.get("error") or ""))
        if hint:
            C.info(f"建议：{hint}")
        return EXIT_TASK
    return EXIT_OK if result["ok"] else EXIT_TASK


if __name__ == "__main__":
    raise SystemExit(main())
