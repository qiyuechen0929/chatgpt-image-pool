"""清场 / 重置：把号池恢复到「干净但保留账号」的状态

什么时候用
----------
- 窗口卡死、插件连不上、状态越跑越乱 → `pool.bat reset`（停止服务 + 关窗口 + 清缓存）
- 想彻底重来（清空窗口池与任务记录，保留卡密/token）→ `pool.bat reset --purge-pool --yes`
- 只想停服务 → `pool.bat stop`

默认**不会**删除：平台账号、卡密、token（这些是你的资产）。

用法
----
    python scripts/reset_pool.py                    # 停服务 + 关窗口 + 清缓存 + 清日志
    python scripts/reset_pool.py --services-only    # 只停服务
    python scripts/reset_pool.py --windows-only     # 只关窗口 + 清缓存
    python scripts/reset_pool.py --purge-pool --yes # 额外清空窗口池绑定与任务记录
    python scripts/reset_pool.py --logs-only
    python scripts/reset_pool.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def all_window_ids(p: C.Paths) -> list[int]:
    try:
        data = C.http_json(f"{p.vb_api_url}/api/getBrowserList", timeout=15).get("data") or []
        return [int(x["id"]) for x in data if str(x.get("id", "")).isdigit()]
    except Exception:
        return []


def running_window_ids(p: C.Paths) -> list[int]:
    try:
        data = C.http_json(f"{p.vb_api_url}/api/getBrowserRunningList", timeout=15).get("data") or []
        return [int(x["id"]) for x in data if str(x.get("id", "")).isdigit()]
    except Exception:
        return []


def close_windows(p: C.Paths, dry: bool) -> tuple[int, int]:
    """关掉正在跑的窗口，并给全部环境清一次缓存（保留 Cookie/登录态）。"""
    running = running_window_ids(p)
    ok = bad = 0
    for wid in running:
        if dry:
            C.info(f"[dry-run] 关闭窗口 id={wid}")
            continue
        try:
            C.http_json(f"{p.vb_api_url}/api/stopBrowser", {"id": wid}, timeout=60)
            ok += 1
        except Exception:
            bad += 1
    ids = all_window_ids(p)
    if ids and not dry:
        cleared = 0
        for wid in ids:
            try:
                C.http_json(f"{p.vb_api_url}/api/clearCache", {"id": wid}, timeout=60)
                cleared += 1
            except Exception:
                pass
        C.info(f"已对 {cleared}/{len(ids)} 个环境执行清缓存（保留 Cookie/登录态）")
    return ok, bad


def clear_logs(p: C.Paths, dry: bool) -> int:
    n = 0
    d = p.log_dir
    if not d.exists():
        return 0
    for f in sorted(d.glob("*.log*")):
        if dry:
            C.info(f"[dry-run] 清空日志 {f.name}")
            continue
        try:
            f.write_bytes(b"")
            n += 1
        except Exception:
            pass
    return n


def purge_pool(p: C.Paths) -> None:
    """清空窗口池绑定与任务记录（保留窗口、账号、token）。"""
    conn = C.sqlite_connect(p.fpb_db)
    try:
        before = conn.execute("SELECT COUNT(*) c FROM task_type_windows").fetchone()["c"]
        conn.execute("UPDATE task_type_windows SET deleted = 1")
        conn.execute("UPDATE tasks SET status = 'canceled' WHERE status IN ('pending', 'processing', 'running')")
        conn.commit()
        C.ok(f"已解绑窗口池 {before} 条，并置进行中任务为 canceled（窗口/账号/token 都保留）")
        C.info("下次导入卡密时会自动重新绑定：pool.bat import accounts.txt --yes --no-create-envs")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="清场 / 重置号池")
    ap.add_argument("--services-only", action="store_true", help="只停服务")
    ap.add_argument("--windows-only", action="store_true", help="只关窗口 + 清缓存")
    ap.add_argument("--logs-only", action="store_true", help="只清日志")
    ap.add_argument("--purge-pool", action="store_true", help="额外解绑窗口池 + 结束进行中任务")
    ap.add_argument("--keep-logs", action="store_true", help="不清日志")
    ap.add_argument("--yes", action="store_true", help="确认执行（--purge-pool 需要）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    p = C.Paths.discover()
    C.title("清场 / 重置号池")

    only = args.services_only or args.windows_only or args.logs_only
    do_services = (args.services_only or not only) and not args.windows_only and not args.logs_only
    do_windows = args.windows_only or not only

    if args.purge_pool and not args.yes:
        C.fail("--purge-pool 会解绑窗口池，请加 --yes 确认（不影响账号/token）")
        return 1

    if do_services:
        import stop_all as S

        C.log("")
        C.info("停止两端服务 ...")
        S.stop_services(p, args.dry_run)

    if do_windows and not C.tcp_listening(p.vb_port):
        C.warn("VirtualBrowser API 未运行，跳过关窗口")
    elif do_windows:
        ok, bad = close_windows(p, args.dry_run)
        if not args.dry_run:
            C.ok(f"已关闭 {ok} 个窗口并清理缓存" + (f"（{bad} 个失败，可忽略）" if bad else ""))

    if args.purge_pool and not args.dry_run:
        purge_pool(p)

    if not args.keep_logs and (args.logs_only or not only):
        n = clear_logs(p, args.dry_run)
        if not args.dry_run:
            C.ok(f"已清空 {n} 个日志文件")

    C.log("")
    C.info("下一步：pool.bat start && pool.bat status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
