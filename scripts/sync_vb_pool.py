"""窗口同步：把 VirtualBrowser 里的指纹环境同步进 FPBrowser2API 空间，并绑定到任务池

做三件事：
  1. 清理本地 DB 里「远端已不存在」的失效窗口（含其任务池绑定）
  2. 从 VirtualBrowser 同步窗口到指定空间
  3. 把同步到的窗口绑定到 gpt_workflow 任务类型的窗口池

为什么需要专门清一次：
    上游 `upsert_windows` 只要发现某个 window_key 已存在于**任意**空间就会跳过
    （防止窗口被误搬到别的空间）。本 skill 的补丁已把它收窄为「只跳过其它空间」，
    但历史遗留的失效窗口仍会挡同步，所以这里主动清一遍。

用法：
    python scripts/sync_vb_pool.py
    python scripts/sync_vb_pool.py --space-pk 5 --task-type-id 6
    python scripts/sync_vb_pool.py --no-bind        # 只同步不绑定
    python scripts/sync_vb_pool.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="VirtualBrowser 窗口 → FPBrowser2API 窗口池")
    ap.add_argument("--space-pk", type=int, default=0, help="空间主键（0=自动识别）")
    ap.add_argument("--task-type-id", type=int, default=0, help="任务类型 ID（0=自动识别 gpt_workflow）")
    ap.add_argument("--remaining-quota", type=int, default=999, help="绑定时的剩余额度初值")
    ap.add_argument("--no-prune", action="store_true", help="不清理失效窗口")
    ap.add_argument("--no-bind", action="store_true", help="不绑定任务池")
    ap.add_argument("--dry-run", action="store_true", help="只显示将执行的操作")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    C.title("窗口同步 / 清理 / 绑定任务池")
    p = C.Paths.discover()

    if not C.tcp_listening(p.vb_port):
        C.fail(f"VirtualBrowser API 未运行（{p.vb_api_url}）→ python scripts/start_all.py")
        return 1
    if not C.tcp_listening(p.fpb_port):
        C.fail(f"FPBrowser2API 未运行（{p.fpb_api_url}）→ python scripts/start_all.py")
        return 1

    # 自动识别空间与任务类型
    conn = C.sqlite_connect(p.fpb_db)
    try:
        auto_space, auto_tt = C.detect_pool_ids(conn)
    finally:
        conn.close()
    space_pk = args.space_pk or auto_space
    task_type_id = args.task_type_id or auto_tt
    if not space_pk:
        C.fail("无法自动识别空间，请用 --space-pk 指定（管理后台「空间」页面可见）")
        return 1
    C.info(f"使用 space_pk={space_pk}，task_type_id={task_type_id or '(不绑定)'}")
    C.log("")

    # 1) 远端环境列表
    remote = C.http_json(f"{p.vb_api_url}/api/getBrowserList", {}, timeout=30).get("data") or []
    remote_keys = {str(r.get("id")) for r in remote if r.get("id") is not None}
    C.info(f"[1/4] VirtualBrowser 环境 {len(remote_keys)} 个")

    # 2) 清理失效窗口（仅本地，不动远端）
    local = C.http_json(f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/windows", token="", timeout=30)
    if local.get("windows") is None:
        # 需要管理员鉴权时走登录
        login = C.http_json(f"{p.fpb_api_url}/api/admin/login", {"username": "admin", "password": "admin"}, timeout=20)
        token = login.get("token") or ""
        local = C.http_json(f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/windows", token=token, timeout=30)
    else:
        token = ""
    local_windows = local.get("windows") or []
    stale = [w for w in local_windows if str(w.get("window_key")) not in remote_keys]
    C.info(f"[2/4] 本地窗口 {len(local_windows)} 个，失效 {len(stale)} 个")
    for w in stale:
        key = str(w.get("window_key"))
        if args.no_prune or args.dry_run:
            C.info(f"      - [跳过] 清理 window_key={key}（{w.get('window_name')}）")
            continue
        try:
            C.http_json(
                f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/windows/{key}/delete",
                {"delete_remote": False, "delete_account": False},
                token=token, timeout=30,
            )
            C.info(f"      - 已清理 window_key={key}（{w.get('window_name')}）")
        except Exception as e:
            C.warn(f"      - 清理 {key} 失败：{e}")

    # 3) 同步
    if args.dry_run:
        C.info("[3/4] dry-run：跳过同步")
    else:
        try:
            rsp = C.http_json(f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/sync-windows", {}, token=token, timeout=120)
            C.info(f"[3/4] {rsp.get('message')}")
            if rsp.get("skipped"):
                C.warn(f"      跳过 {rsp.get('skipped')} 个：{rsp.get('skipped_keys')}")
        except Exception as e:
            C.fail(f"同步失败：{e}")
            return 1

    # 4) 绑定任务池
    local = C.http_json(f"{p.fpb_api_url}/api/admin/spaces/{space_pk}/windows", token=token, timeout=30)
    windows = [w for w in (local.get("windows") or []) if str(w.get("window_key")) in remote_keys]
    C.info(f"[4/4] 待绑定窗口 {len(windows)} 个")
    if args.no_bind or not task_type_id:
        C.info("      已跳过绑定")
        return 0
    if args.dry_run:
        C.info("      dry-run：跳过绑定")
        return 0
    if not windows:
        C.warn("      没有可绑定窗口")
        return 0
    pks = [int(w["id"]) for w in windows]
    try:
        rsp = C.http_json(
            f"{p.fpb_api_url}/api/admin/task-types/{task_type_id}/windows",
            {"window_pks": pks, "enabled": True, "daily_quota": 0, "remaining_quota": args.remaining_quota},
            token=token, timeout=60,
        )
        C.ok(f"      已绑定到任务类型 {task_type_id}：affected={rsp.get('affected')}")
    except Exception as e:
        C.fail(f"绑定失败：{e}")
        return 1

    # 复核
    C.log("")
    conn = C.sqlite_connect(p.fpb_db)
    try:
        rows = conn.execute(
            """
            SELECT w.window_key, w.window_name, w.platform_account, tc.enabled
            FROM task_type_windows tc JOIN windows w ON w.id = tc.window_pk
            WHERE tc.task_type_id = ? AND tc.deleted = 0 AND w.deleted = 0 ORDER BY w.id
            """,
            (task_type_id,),
        ).fetchall()
        C.ok(f"任务类型 {task_type_id} 窗口池现有 {len(rows)} 条")
        for r in rows[:25]:
            C.info(f"win={r['window_key']:<4} {str(r['window_name'])[:22]:<24} {str(r['platform_account'] or '-')[:32]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
