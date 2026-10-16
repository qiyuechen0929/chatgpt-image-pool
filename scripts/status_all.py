"""状态看板：服务 / 环境 / 插件长连接 / 窗口池 / token 有效期 / 最近任务

用法：
    python scripts/status_all.py
    python scripts/status_all.py --tasks 10     # 多看几条最近任务
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def line(title: str) -> None:
    C.log("")
    C.log(f"── {title} " + "─" * max(0, 60 - len(title)))


def main() -> int:
    ap = argparse.ArgumentParser(description="生图号池状态看板")
    ap.add_argument("--tasks", type=int, default=5, help="显示最近多少条任务")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    C.title("生图号池 状态看板")
    p = C.Paths.discover()

    vb_up = C.tcp_listening(p.vb_port)
    fpb_up = C.tcp_listening(p.fpb_port)

    line("服务")
    C.log(f"  {'[OK]' if vb_up else '[--]'} VirtualBrowser API   {p.vb_api_url}")
    C.log(f"  {'[OK]' if fpb_up else '[--]'} FPBrowser2API        {p.fpb_api_url}")
    if not vb_up or not fpb_up:
        C.log("")
        C.warn("有服务未运行 → python scripts/start_all.py")
        return 1

    # VirtualBrowser
    try:
        vb = C.http_json(f"{p.vb_api_url}/api/getBrowserList", timeout=8)
        envs = vb.get("data") or []
        running = C.http_json(f"{p.vb_api_url}/api/getBrowserRunningList", timeout=8).get("data") or []
        exts = C.http_json(f"{p.vb_api_url}/api/getCrxList", timeout=8).get("data") or []
        line("VirtualBrowser")
        C.log(f"  指纹环境：{len(envs)} 个    运行中窗口：{len(running)} 个")
        if running:
            C.log("      " + ", ".join(f"id={r.get('id')}(:{r.get('port')})" for r in running[:12]))
        C.log(f"  已注入插件：{[e.get('name') for e in exts]}")
    except Exception as e:
        C.warn(f"读取 VirtualBrowser 信息失败：{e}")

    # 插件长连接
    try:
        clients = C.http_json(f"{p.fpb_api_url}/api/extension/clients", timeout=8).get("clients") or []
        line("插件长连接")
        C.log(f"  在线窗口：{len(clients)} 个")
        if clients:
            C.log("      " + ", ".join(str(c.get("window_key")) for c in clients[:20]))
    except Exception as e:
        C.warn(f"读取插件客户端失败：{e}")

    # 数据库
    try:
        conn = C.sqlite_connect(p.fpb_db)
    except SystemExit as e:
        C.warn(str(e))
        return 1

    try:
        space_pk, task_type_id = C.detect_pool_ids(conn)
        cfg = conn.execute("SELECT api_key FROM system_config WHERE id = 1").fetchone()
        line("配置")
        C.log(f"  公开 API Key：{cfg['api_key'] if cfg else '(未设置)'}")
        C.log(f"  空间 space_pk={space_pk}    任务类型 task_type_id={task_type_id}")

        rows = conn.execute(
            """
            SELECT w.window_key, w.window_name, w.platform_account, w.proxy_addr,
                   tc.enabled, tc.remaining_quota, tc.sora_access_token, tc.sora_access_expires,
                   tc.consecutive_errors, tc.error_cooldown_until
            FROM task_type_windows tc JOIN windows w ON w.id = tc.window_pk
            WHERE tc.task_type_id = ? AND tc.deleted = 0 AND w.deleted = 0
            ORDER BY w.id
            """,
            (task_type_id,),
        ).fetchall()
        line(f"窗口池（任务类型 {task_type_id}）")
        C.log(f"  绑定 {len(rows)} 条，启用 {sum(1 for r in rows if r['enabled'])} 条")
        now = time.time()
        expiring = 0
        expired = 0
        for r in rows:
            tok = (r["sora_access_token"] or "").strip()
            exp = C.jwt_exp(tok) if tok else 0
            if tok and exp and exp < now:
                expired += 1
            elif tok and exp and exp - now < 2 * 86400:
                expiring += 1
        C.log(f"  带 token：{sum(1 for r in rows if (r['sora_access_token'] or '').strip())} 条"
              f"（已过期 {expired}，2 天内到期 {expiring}）")
        C.log("")
        C.log(f"  {'窗口':<6}{'环境名':<22}{'账号':<34}{'启用':<6}{'额度':<7}{'token 到期':<22}冷却")
        for r in rows:
            tok = (r["sora_access_token"] or "").strip()
            exp = C.jwt_exp(tok) if tok else 0
            exp_txt = time.strftime("%Y-%m-%d %H:%M", time.localtime(exp)) if exp else "-"
            C.log(
                f"  {str(r['window_key']):<6}{str(r['window_name'])[:20]:<22}"
                f"{str(r['platform_account'] or '-')[:32]:<34}"
                f"{('是' if r['enabled'] else '否'):<6}{str(r['remaining_quota']):<7}{exp_txt:<22}"
                f"{r['error_cooldown_until'] or ''}"
            )

        tasks = conn.execute(
            "SELECT task_id, status, progress, window_pk, created_at, error_message FROM tasks "
            "ORDER BY id DESC LIMIT ?",
            (max(1, args.tasks),),
        ).fetchall()
        line(f"最近 {len(tasks)} 条任务")
        for t in tasks:
            err = (t["error_message"] or "").replace("\n", " ")[:52]
            C.log(f"  {t['created_at']}  {str(t['status']):<10} {str(t['progress']):>3}%  win_pk={t['window_pk']}  {err}")
    finally:
        conn.close()

    C.log("")
    C.log("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
