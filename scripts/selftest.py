"""端到端自检：真出一张图，验证「我到底装好了没有」

doctor 只检查环境是否具备，本脚本会**真的跑一次完整链路**：
选窗口 → 提交任务 → 等生成 → 用窗口 token 下载原图 → 校验是张真图片。

用法
----
    python scripts/selftest.py                 # 出一张 1:1 的图并存到 output/selftest.png
    python scripts/selftest.py --res 2k --ratio 16:9
    python scripts/selftest.py --json          # 机器可读结果

退出码：0 自检通过 / 1 环境未就绪 / 2 任务失败 / 3 图片下载失败
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402
import gen_image as G  # noqa: E402

TEST_PROMPT = "自检用图：一只戴宇航头盔的柴犬，扁平插画风，纯色背景"


def preflight(p: C.Paths) -> list[str]:
    """返回问题列表（空表示就绪）。"""
    problems: list[str] = []
    if not C.tcp_listening(p.vb_port):
        problems.append(f"VirtualBrowser API 未监听 {p.vb_port} → pool.bat start")
    if not C.tcp_listening(p.fpb_port):
        problems.append(f"FPBrowser2API 未监听 {p.fpb_port} → pool.bat start")
    if problems:
        return problems
    try:
        conn = C.sqlite_connect(p.fpb_db)
        space_pk, tt = C.resolve_pool_targets(p, conn)
        rows = conn.execute(
            """
            SELECT COUNT(*) AS c FROM task_type_windows tc
            JOIN windows w ON w.id = tc.window_pk
            WHERE tc.task_type_id = ? AND tc.deleted = 0 AND tc.enabled = 1
              AND w.deleted = 0 AND COALESCE(tc.sora_access_token, '') <> ''
            """,
            (tt,),
        ).fetchone()
        n = int(rows["c"]) if rows else 0
        conn.close()
        if n == 0:
            problems.append(
                "号池里没有可用窗口（带 token 且启用）→ 先导入卡密：\n"
                "      pool.bat import accounts.txt --yes\n"
                "      然后预热：pool.bat warm"
            )
    except SystemExit as e:
        problems.append(str(e))
    except Exception as e:
        problems.append(f"读数据库失败：{e}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="端到端自检（真出一张图）")
    ap.add_argument("-o", "--output", default="", help="图片保存路径（默认 output/selftest.png）")
    ap.add_argument("--ratio", default="1:1")
    ap.add_argument("--res", default="1k", choices=["1k", "2k", "4k"])
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    p = C.Paths.discover()
    out = Path(args.output) if args.output else C.SKILL_ROOT / "output" / "selftest.png"

    if not args.json:
        C.title("端到端自检")
        C.log(f"  输出：{out}")

    problems = preflight(p)
    if problems:
        if args.json:
            print(json.dumps({"ok": False, "stage": "preflight", "problems": problems}, ensure_ascii=False))
        else:
            for x in problems:
                C.fail(x)
            C.log("")
            C.info("先把上面的问题解决，再跑一次：pool.bat test")
        return 1

    t0 = time.time()
    try:
        result = G.generate_one(
            p=p,
            api_url=p.fpb_api_url,
            api_key=C.fpb_api_key(p),
            prompt=TEST_PROMPT,
            out_path=out,
            ratio=args.ratio,
            res=args.res,
            raw_prompt=True,  # 自检要走最直白的路径，不依赖提示词扩写
            timeout=args.timeout,
            poll=5.0,
            quiet=args.json,
            retries=2,
        )
    except Exception as e:
        msg = str(e)
        if args.json:
            print(json.dumps({"ok": False, "stage": "run", "error": msg, "hint": G.diagnose(msg)}, ensure_ascii=False))
        else:
            C.fail(f"自检失败：{msg}")
            hint = G.diagnose(msg)
            if hint:
                C.info(f"建议：{hint}")
        return 2 if "下载" not in msg else 3

    elapsed = time.time() - t0
    payload = {
        "ok": bool(result.get("ok")),
        "elapsed_seconds": round(elapsed, 1),
        "saved_path": result.get("saved_path"),
        "bytes": result.get("bytes"),
        "task_id": result.get("task_id"),
        "attempts": result.get("attempts"),
        "error": result.get("error"),
    }
    if not result.get("ok"):
        hint = G.diagnose(str(result.get("error") or ""))
        payload["hint"] = hint
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            C.fail(f"任务失败：{result.get('error')}（任务号 {result.get('task_id')}）")
            if hint:
                C.info(f"建议：{hint}")
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    size = float(result.get("bytes") or 0)
    C.log("")
    C.log("-" * 68)
    C.ok(f"自检通过：{result['saved_path']}（{C.human_bytes(size)}，{elapsed:.0f}s，第 {result.get('attempts')} 次成功）")
    if result.get("attempts", 1) > 1:
        C.info("提示：第一次模型只回了文字，已自动加固提示词重试成功（免费号偶发，属正常）。")
    C.log("")
    C.log("  接下来可以这样用：")
    C.log('    pool.bat gen "你的提示词" --ratio 1:1 -o out.png')
    C.log("    pool.bat batch prompts.txt --outdir output --concurrency 3")
    C.log(f"    POST {p.fpb_api_url}/v1/videos  （程序化调用，见 docs/05-daily-use.md）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
