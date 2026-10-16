"""启动两个后端服务（**无窗口后台运行**，日志落盘）

为什么要无窗口：
    早期版本把服务跑在可见的控制台窗口里，随手一关服务就没了，
    表现为任务莫名其妙失败（“浏览器插件未连接” / 连接被拒绝）。
    这里用 DETACHED_PROCESS 启动，进程独立于终端，日志写到 logs/ 目录。

行为：
    - 端口已在监听 → 跳过（不会重复拉起）
    - 启动后轮询等待就绪，最多 --wait 秒
    - 可选 --open-client 同时拉起 VirtualBrowser 客户端（仅 Windows）

用法：
    python scripts/start_all.py
    python scripts/start_all.py --wait 60 --open-client
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

IS_WIN = sys.platform.startswith("win")


def spawn_detached(cmd: list[str], cwd: Path, out_log: Path, err_log: Path) -> int:
    """后台启动，不带控制台窗口（Windows）/ 脱离会话（POSIX）。启动前做日志轮转。"""
    out_log.parent.mkdir(parents=True, exist_ok=True)
    C.rotate_log(err_log)  # 防止日志无限增长占满磁盘
    C.rotate_log(out_log)
    out = open(out_log, "ab")
    err = open(err_log, "ab")
    kwargs: dict = dict(cwd=str(cwd), stdout=out, stderr=err, stdin=subprocess.DEVNULL, close_fds=True)
    if IS_WIN:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return proc.pid


def main() -> int:
    ap = argparse.ArgumentParser(description="启动 AI 生图号池全部服务（后台无窗口）")
    ap.add_argument("--wait", type=float, default=60.0, help="等待就绪的上限秒数")
    ap.add_argument("--open-client", action="store_true", help="同时启动 VirtualBrowser 客户端（Windows）")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    C.title("启动 生图号池 服务")
    p = C.Paths.discover()
    C.log(p.report())
    C.log("")

    started: list[str] = []

    # ---- 1) VirtualBrowser 本地 API ----
    if C.tcp_listening(p.vb_port):
        C.ok(f"VirtualBrowser API 已在运行（端口 {p.vb_port}），跳过")
    elif not p.vb_api_server:
        C.fail("未找到 VirtualBrowser api_server（server.py）→ 见 docs/02-install.md")
    else:
        pid = spawn_detached(
            [str(p.vb_python), "server.py"],
            cwd=p.vb_api_server,
            out_log=p.log_dir / "vb_api.out.log",
            err_log=p.log_dir / "vb_api.err.log",
        )
        C.ok(f"已启动 VirtualBrowser API（pid={pid}，日志 {p.log_dir / 'vb_api.out.log'}）")
        started.append("vb")

    # ---- 2) FPBrowser2API ----
    if C.tcp_listening(p.fpb_port):
        C.ok(f"FPBrowser2API 已在运行（端口 {p.fpb_port}），跳过")
    elif not p.fpb_root:
        C.fail("未找到 FPBrowser2API 根目录 → 设置 FPB_ROOT 或见 docs/02-install.md")
    else:
        pid = spawn_detached(
            [str(p.fpb_python), "main.py"],
            cwd=p.fpb_root,
            out_log=p.log_dir / "fpb.out.log",
            err_log=p.log_dir / "fpb.err.log",
        )
        C.ok(f"已启动 FPBrowser2API（pid={pid}，日志 {p.log_dir / 'fpb.out.log'}）")
        started.append("fpb")

    # ---- 3) VirtualBrowser 客户端（可选）----
    if args.open_client and IS_WIN:
        exe = None
        if p.vb_root and (p.vb_root / "VirtualBrowser.exe").exists():
            exe = p.vb_root / "VirtualBrowser.exe"
        if exe:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
            C.ok("已启动 VirtualBrowser 客户端（仅用于查看/管理环境，请勿用它手动启动窗口）")
        else:
            C.warn("未找到 VirtualBrowser.exe，跳过客户端启动")

    # ---- 4) 等待就绪 ----
    C.log("")
    C.info("等待服务就绪 ...")
    deadline = time.time() + max(5.0, args.wait)
    while time.time() < deadline:
        vb = C.tcp_listening(p.vb_port)
        fpb = C.tcp_listening(p.fpb_port)
        if vb and fpb:
            break
        time.sleep(1.5)

    vb_ok = C.tcp_listening(p.vb_port)
    fpb_ok = C.tcp_listening(p.fpb_port)
    C.log("")
    (C.ok if vb_ok else C.fail)(f"VirtualBrowser API  : {p.vb_api_url}")
    (C.ok if fpb_ok else C.fail)(f"FPBrowser2API       : {p.fpb_api_url}")

    if not (vb_ok and fpb_ok):
        C.log("")
        C.warn("有服务未就绪，下面直接展示日志尾部（并在能识别时给出原因）：")
        for name, logf, alive in (
            ("VirtualBrowser API", p.log_dir / "vb_api.err.log", vb_ok),
            ("FPBrowser2API", p.log_dir / "fpb.err.log", fpb_ok),
        ):
            if alive:
                continue
            C.log("")
            C.log(f"── {name} 日志：{logf} " + "─" * 10)
            hint = C.dependency_problem(logf)
            if hint:
                C.fail(f"原因很可能是：{hint}")
            tail = C.tail_file(logf, lines=12)
            C.log(tail or "  (日志为空：可能是进程根本没起得来，用 pool.bat doctor 看依赖是否完整)")
        C.log("")
        C.info("完整体检：pool.bat doctor")
        return 1

    C.log("")
    C.log('  下一步：pool.bat test        （端到端自检：真出一张图）')
    C.log("  状态：  pool.bat status")
    C.log("  出图：  pool.bat gen \"一只柴犬宇航员\" -o out.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
