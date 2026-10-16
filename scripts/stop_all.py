"""停止服务（默认连指纹窗口一起关）

用法：
    python scripts/stop_all.py                # 关所有指纹窗口 + 停两个服务
    python scripts/stop_all.py --keep-windows # 只停服务，保留指纹窗口
    python scripts/stop_all.py --dry-run      # 只看会做什么
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

IS_WIN = sys.platform.startswith("win")


def stop_windows(p: C.Paths, dry: bool) -> int:
    if not C.tcp_listening(p.vb_port):
        C.info("VirtualBrowser API 未运行，跳过窗口清理")
        return 0
    try:
        rows = C.http_json(f"{p.vb_api_url}/api/getBrowserRunningList", timeout=8).get("data") or []
    except Exception as e:
        C.warn(f"读取运行中窗口失败：{e}")
        return 0
    if not rows:
        C.info("没有正在运行的指纹窗口")
        return 0
    n = 0
    for row in rows:
        wid = row.get("id")
        if dry:
            C.info(f"[dry-run] 将关闭窗口 id={wid}")
            continue
        try:
            C.http_json(f"{p.vb_api_url}/api/stopBrowser", {"id": wid}, timeout=60)
            C.info(f"已关闭窗口 id={wid}")
            n += 1
        except Exception as e:
            C.warn(f"关闭窗口 id={wid} 失败：{e}")
    return n


def _list_service_pids(p: C.Paths) -> list[tuple[int, str]]:
    """找出本项目的服务进程（按命令行特征），返回 [(pid, cmdline)]。"""
    patterns = []
    if p.fpb_root:
        patterns.append(("main.py", str(p.fpb_root).lower()))
    if p.vb_api_server:
        patterns.append(("server.py", str(p.vb_api_server).lower()))

    found: list[tuple[int, str]] = []
    if IS_WIN:
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except Exception as e:
            C.warn(f"枚举进程失败：{e}")
            return []
        for line in out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2 or not parts[0].strip().isdigit():
                continue
            pid, cmd = int(parts[0].strip()), parts[1]
            low = cmd.lower()
            for script, marker in patterns:
                if script in low and marker in low:
                    found.append((pid, cmd))
                    break
    else:
        for proc in Path("/proc").glob("[0-9]*"):
            try:
                cmd = (proc / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
            except Exception:
                continue
            low = cmd.lower()
            for script, marker in patterns:
                if script in low and marker in low:
                    found.append((int(proc.name), cmd))
                    break
    return found


def stop_services(p: C.Paths, dry: bool) -> int:
    procs = _list_service_pids(p)
    if not procs:
        C.info("两个服务都不在运行")
        return 0
    n = 0
    for pid, cmd in procs:
        if dry:
            C.info(f"[dry-run] 将结束 pid={pid}（{cmd[:70]}...）")
            continue
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
            else:
                subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=30)
            C.info(f"已结束服务进程 pid={pid}")
            n += 1
        except Exception as e:
            C.warn(f"结束 pid={pid} 失败：{e}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="停止 AI 生图号池服务")
    ap.add_argument("--keep-windows", action="store_true", help="保留指纹窗口，只停服务")
    ap.add_argument("--dry-run", action="store_true", help="只显示将执行的操作")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    C.title("停止 生图号池 服务")
    p = C.Paths.discover()

    C.log("")
    C.info("[1/2] 指纹窗口")
    if args.keep_windows:
        C.info("已按 --keep-windows 跳过")
    else:
        stop_windows(p, args.dry_run)

    C.log("")
    C.info("[2/2] 后端服务")
    n = stop_services(p, args.dry_run)

    C.log("")
    if args.dry_run:
        C.info("dry-run 结束，未做任何修改")
    else:
        C.ok(f"完成，共结束 {n} 个服务进程")
        C.info("提示：VirtualBrowser 客户端不会被关闭，可继续查看环境")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
