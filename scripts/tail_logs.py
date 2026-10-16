"""查看服务日志尾部（跨平台，不依赖 PowerShell 或硬编码盘符）

用法：
    python scripts/tail_logs.py            # 各日志最后 20 行
    python scripts/tail_logs.py --lines 50
    python scripts/tail_logs.py --errors   # 只显示含 ERROR/Traceback/FAIL 的行
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

INTERESTING = ("Traceback", "ERROR", "Error", "FAIL", "Exception", "CRITICAL", "WARN")


def main() -> int:
    ap = argparse.ArgumentParser(description="查看服务日志")
    ap.add_argument("--lines", type=int, default=20, help="每个日志显示多少行")
    ap.add_argument("--errors", action="store_true", help="只显示错误相关行")
    ap.add_argument("--dir", default="", help="日志目录（默认自动定位）")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    p = C.Paths.discover()
    d = Path(args.dir) if args.dir else p.log_dir
    C.title("服务日志")
    C.log(f"  目录：{d}")
    if not d.exists():
        C.warn("日志目录不存在（服务没启动过？先 pool.bat start）")
        return 1

    logs = sorted(d.glob("*.log"))
    if not logs:
        C.warn("目录里没有 .log 文件")
        return 1

    empty = 0
    for f in logs:
        size = f.stat().st_size
        C.log("")
        C.log(f"── {f.name}（{C.human_bytes(size)}）" + "─" * 12)
        if size == 0:
            C.info("(空)")
            empty += 1
            continue
        if args.errors:
            text = C.tail_file(f, lines=400, max_chars=200000)
            hits = [ln for ln in text.splitlines() if any(k in ln for k in INTERESTING)]
            if hits:
                C.log("\n".join(hits[-args.lines :]))
            else:
                C.info("(没有错误相关行)")
        else:
            C.log(C.tail_file(f, lines=args.lines) or "(空)")

    if empty == len(logs):
        C.log("")
        C.info("全部日志为空：通常是依赖没装好导致进程秒退 → pool.bat doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
