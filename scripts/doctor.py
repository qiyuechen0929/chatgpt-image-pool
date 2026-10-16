"""一键环境自检（doctor）—— 新装/迁移/出问题时第一条命令

检查项：
  1. Python 版本与依赖
  2. 路径解析（FPBrowser2API / VirtualBrowser / 数据库）
  3. 上游补丁是否已打（逐文件核对关键标记）
  4. 两个服务是否在跑 + HTTP 健康
  5. VirtualBrowser：内核可执行文件存在、扩展已注册
  6. FPBrowser2API：扩展桥配置、公开 API Key、/v1/models 可用
  7. 号池数据库：空间/任务类型/窗口池/可用 token（含过期预警）
  8. 当前插件长连接数量

用法：
    python scripts/doctor.py
    python scripts/doctor.py --no-network     # 跳过 /v1/models 等网络检查
退出码：0 = 无 FAIL；1 = 有 FAIL
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

FAILED: list[str] = []
WARNED: list[str] = []


def _fail(msg: str) -> None:
    C.fail(msg)
    FAILED.append(msg)


def _warn(msg: str) -> None:
    C.warn(msg)
    WARNED.append(msg)


# 补丁标记：(归属, 相对路径, 标记片段, 说明)  归属：vb=VirtualBrowser api_server 目录 / fpb=FPBrowser2API 根目录
PATCH_MARKERS = [
    ("vb", "core.py", "_looks_like_core", "内核路径探测（支持自定义安装目录）"),
    ("vb", "core.py", "def _list_worker_pids", "残留窗口进程检测（PowerShell CIM 替代 wmic）"),
    ("vb", "core.py", "do_randomize_fingerprint", "补齐 /api/randomizeFingerprint、/api/clearCache、/api/isBrowserRunning"),
    ("vb", "server.py", "/api/isBrowserRunning", "补齐 FPBrowser2API 兼容接口"),
    ("fpb", "src/core/database.py", "space_pk != ?", "修复同空间窗口同步被判为「跨空间」而跳过"),
    ("fpb", "src/core/config.py", "extension_connect_wait_seconds", "插件连接等待可配置"),
    ("fpb", "src/services/gpt_task_executor.py", "_gpt_extension_connect_wait", "任务使用可配置的插件等待时间"),
    ("fpb", "src/services/fp_browser_client.py", "window_remark", "窗口备注/账号字段映射到窗口池"),
    ("fpb", "skills/chatgpt-image-gen/scripts/generate_image.py", "File stream access denied", "结果图改用窗口 token 下载并校验"),
]


def section(name: str) -> None:
    C.log("")
    C.log(f"── {name} " + "─" * max(0, 60 - len(name)))


def check_python() -> None:
    section("1. Python 与依赖")
    v = sys.version_info
    C.info(f"当前解释器：{sys.executable}")
    C.info(f"版本：{v.major}.{v.minor}.{v.micro}")
    if v < (3, 10):
        _fail("Python 版本过低（需要 3.10+，推荐 3.11/3.12）")
    else:
        C.ok("Python 版本满足要求（>=3.10）")

    if C.IS_WINDOWS and sys.platform == "win32":
        major, minor = sys.getwindowsversion()[:2]
        build = sys.getwindowsversion().build
        C.info(f"Windows：{major}.{minor} build {build}")
        if build >= 26200:
            C.ok("已为新系统准备（wmic 缺失不影响，补丁里已改用 PowerShell CIM）")


def check_paths(p: C.Paths) -> None:
    section("2. 路径解析")
    C.log(p.report())
    for n in p.notes:
        _warn(f"注意：{n}")
    if p.fpb_root:
        C.ok("已定位 FPBrowser2API")
    else:
        _fail("未找到 FPBrowser2API 代码目录（设置 FPB_ROOT）")

    if p.vb_api_server:
        C.ok("已定位 VirtualBrowser 本地 API 服务目录")
    else:
        _fail("未找到 VirtualBrowser api_server（server.py）")

    if p.fpb_db and p.fpb_db.exists():
        C.ok("已找到任务数据库")
    else:
        _warn("未找到 data/fpbrowser.db（FPBrowser2API 启动过一次就会生成）")

    if p.python:
        C.ok(f"已找到项目 venv Python：{p.python}")
    else:
        _warn("未找到项目 venv，脚本将使用当前解释器（建议按 docs/02-install.md 建 venv）")


def check_patches(p: C.Paths) -> None:
    section("3. 上游补丁是否已打")
    missing = []
    for kind, rel, marker, desc in PATCH_MARKERS:
        base = p.vb_api_server if kind == "vb" else p.fpb_root
        if base is None:
            missing.append((rel, desc))
            continue
        target = base / rel
        if not target.exists():
            missing.append((rel, desc))
            continue
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        if marker in text:
            C.ok(f"{rel}  ✓ {desc}")
        else:
            missing.append((rel, desc))
            C.fail(f"{rel}  ✗ 缺少：{desc}")
    if missing:
        _fail(f"有 {len(missing)} 处补丁未打 → git apply --ignore-whitespace patches/*.patch（见 patches/README.md）")


def check_services(p: C.Paths, network: bool) -> tuple[bool, bool]:
    section("4. 服务运行状态")
    vb_up = C.tcp_listening(p.vb_port)
    fpb_up = C.tcp_listening(p.fpb_port)

    if vb_up:
        C.ok(f"VirtualBrowser API {p.vb_api_url} 端口已监听")
        try:
            rsp = C.http_json(f"{p.vb_api_url}/api/getBrowserList", timeout=6)
            C.ok(f"接口可用：环境数 {rsp.get('total')}")
        except Exception as e:
            _fail(f"接口不可用：{e}")
    else:
        _fail(f"VirtualBrowser API 未监听 {p.vb_port} → 运行 pool.bat start")

    if fpb_up:
        C.ok(f"FPBrowser2API {p.fpb_api_url} 端口已监听")
        try:
            rsp = C.http_json(f"{p.fpb_api_url}/api/extension/clients", timeout=6)
            C.ok(f"接口可用：已连接插件客户端 {len(rsp.get('clients') or [])} 个")
        except Exception as e:
            _fail(f"接口不可用：{e}")
    else:
        _fail(f"FPBrowser2API 未监听 {p.fpb_port} → 运行 pool.bat start")

    if network and fpb_up:
        check_public_api(p)
    return vb_up, fpb_up


def check_public_api(p: C.Paths) -> None:
    section("5. 公开 API 与 Key")
    key = None
    try:
        conn = C.sqlite_connect(p.fpb_db)
        row = conn.execute("SELECT api_key FROM system_config WHERE id = 1").fetchone()
        if row:
            key = row["api_key"]
        conn.close()
    except Exception as e:
        _warn(f"读取 system_config 失败：{e}")

    if not key:
        _warn("未读到公开 API Key（可稍后在管理后台设置）")
        return
    C.info(f"公开 API Key：{key}")
    try:
        rsp = C.http_json(f"{p.fpb_api_url}/v1/models", token=key, timeout=10)
        models = [m.get("id") for m in (rsp.get("data") or [])]
        img = [m for m in models if str(m).startswith("gpt-image2")]
        C.ok(f"/v1/models 可用，共 {len(models)} 个模型；gpt-image2 系列：{img}")
    except Exception as e:
        _fail(f"/v1/models 调用失败（Key 不正确或服务异常）：{e}")


def check_virtualbrowser(p: C.Paths) -> None:
    section("6. VirtualBrowser")
    # 内核可执行文件
    exe_env = (C.os.environ.get("VB_BROWSER_EXE") or "").strip()
    found_exe = None
    if exe_env and Path(exe_env).exists():
        found_exe = Path(exe_env)
    if p.vb_root:
        for cand in [p.vb_root / "VirtualBrowser.exe"]:
            if cand.exists():
                found_exe = cand
        core_base = p.vb_root / "VirtualBrowser"
        if core_base.exists():
            for child in sorted(core_base.iterdir(), reverse=True):
                if child.is_dir() and (child / "VirtualBrowser.exe").exists():
                    found_exe = child / "VirtualBrowser.exe"
                    break
    if found_exe:
        C.ok(f"内核可执行文件：{found_exe}")
    else:
        _warn("未直接找到内核 exe（若服务已在运行可忽略；否则设置 VB_BROWSER_EXE）")

    if not C.tcp_listening(p.vb_port):
        return
    try:
        exts = C.http_json(f"{p.vb_api_url}/api/getCrxList", timeout=6).get("data") or []
        names = [e.get("name") for e in exts]
        if exts:
            C.ok(f"已注册插件：{names}")
        else:
            _fail("没有注册任何插件 → 需要注册 FPBrowser2API 扩展（见 docs/03-configure.md）")
        for e in exts:
            path = str(e.get("path") or "")
            if path and not Path(path).exists():
                _fail(f"插件路径不存在：{path}")
    except Exception as e:
        _warn(f"读取插件列表失败：{e}")


def check_pool(p: C.Paths) -> None:
    section("7. 号池数据库")
    if not (p.fpb_db and p.fpb_db.exists()):
        return
    conn = C.sqlite_connect(p.fpb_db)
    try:
        space_pk, task_type_id = C.detect_pool_ids(conn)
        C.info(f"识别到空间 space_pk={space_pk}，任务类型 task_type_id={task_type_id}（gpt_workflow）")
        if not task_type_id:
            _warn("未找到 gpt_workflow 任务类型")
            return

        windows = conn.execute(
            "SELECT COUNT(*) n FROM windows WHERE space_pk = ? AND deleted = 0", (space_pk,)
        ).fetchone()["n"]
        C.info(f"窗口数：{windows}")

        rows = conn.execute(
            """
            SELECT w.window_key, w.platform_account, tc.enabled, tc.sora_access_token, tc.sora_access_expires,
                   tc.consecutive_errors, tc.error_cooldown_until
            FROM task_type_windows tc JOIN windows w ON w.id = tc.window_pk
            WHERE tc.task_type_id = ? AND tc.deleted = 0 AND w.deleted = 0
            ORDER BY w.id
            """,
            (task_type_id,),
        ).fetchall()
        if not rows:
            _fail("任务池是空的 → 运行 scripts/import_chatgpt_tokens.py 或 pool.bat sync")
            return

        enabled = [r for r in rows if r["enabled"]]
        with_token = [r for r in rows if (r["sora_access_token"] or "").strip()]
        C.ok(f"任务池绑定 {len(rows)} 条，启用 {len(enabled)} 条，带 token {len(with_token)} 条")

        now = time.time()
        soon, expired, bad = [], [], []
        for r in with_token:
            exp = C.jwt_exp(r["sora_access_token"])
            if exp <= 0:
                bad.append(r)
            elif exp < now:
                expired.append(r)
            elif exp - now < 2 * 86400:
                soon.append(r)
        if expired:
            _fail(f"{len(expired)} 个 token 已过期 → 重新导入新卡密（pool.bat import-accounts accounts.txt）")
        if soon:
            _warn(f"{len(soon)} 个 token 将在 2 天内过期（示例：{soon[0]['platform_account']}）")
        if bad:
            _warn(f"{len(bad)} 个 token 无法解析 exp（可能不是标准 JWT）")
        if with_token and not expired:
            C.ok("token 有效期正常")

        cooling = [r for r in rows if r["error_cooldown_until"]]
        if cooling:
            C.info(f"处于错误冷却中的窗口：{len(cooling)} 个（首个解冻时间 {cooling[0]['error_cooldown_until']}）")

        # 账号表
        try:
            acc = conn.execute("SELECT COUNT(*) n FROM platform_accounts WHERE deleted = 0").fetchone()["n"]
            C.info(f"平台账号表：{acc} 条")
        except Exception:
            pass
    finally:
        conn.close()


def check_extension_bridge(p: C.Paths) -> None:
    if not C.tcp_listening(p.fpb_port):
        return
    section("8. 插件长连接")
    try:
        clients = C.http_json(f"{p.fpb_api_url}/api/extension/clients", timeout=6).get("clients") or []
        if clients:
            C.ok(f"当前在线窗口 {len(clients)} 个：{[c.get('window_key') for c in clients][:10]}")
        else:
            C.warn("当前没有窗口在线（正常，任务时会自动拉起）")
    except Exception as e:
        _warn(f"读取插件客户端失败：{e}")

    cfg = C.read_setting_toml(p)
    ext = cfg.get("extension_executor", {}) if cfg else {}
    if not ext.get("enabled"):
        _fail("[extension_executor].enabled 不是 true → 长连接执行器未启用")
    else:
        C.ok("[extension_executor].enabled = true")
    if not str(ext.get("base_url") or "").strip():
        _warn("[extension_executor].base_url 为空（插件将按服务端口推导）")
    else:
        C.info(f"[extension_executor].base_url = {ext.get('base_url')}")


def check_runtime_extras(p: C.Paths) -> None:
    """预热/自动化开窗依赖 + 浏览器扩展是否已装（新手最常见的两个坑）。"""
    section("9. 预热依赖与浏览器扩展")
    # playwright：预热/开窗必需
    for label, root in (("VirtualBrowser", p.vb_api_server), ("FPBrowser2API", p.fpb_root)):
        if not root:
            continue
        py = None
        for cand in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
            if cand.exists():
                py = cand
                break
        if not py:
            continue
        if C.module_available(py, "playwright"):
            C.ok(f"{label} 的 playwright 可用（预热/开窗需要）")
        else:
            _fail(f"{label} 缺 playwright → 预热会失败：{py} -m pip install playwright")

    # 浏览器扩展
    if not p.vb_root:
        return
    dst = p.vb_root / "extensions" / "fp_browser_extension"
    src = (p.fpb_root / "browser_extension") if p.fpb_root else None
    if dst.exists():
        C.ok(f"浏览器扩展已安装：{dst}")
        try:
            import re as _re

            dv = _re.search(r'"version"\s*:\s*"([^"]+)"', (dst / "manifest.json").read_text(encoding="utf-8", errors="replace"))
            C.info(f"安装版本：{dv.group(1) if dv else '未知'}")
            if src and (src / "manifest.json").exists():
                sv = _re.search(r'"version"\s*:\s*"([^"]+)"', (src / "manifest.json").read_text(encoding="utf-8", errors="replace"))
                if sv and dv and sv.group(1) != dv.group(1):
                    _warn(f"源码版本 {sv.group(1)} 与安装版本不一致 → pool.bat setup（或 --force-extension）可更新")
        except Exception:
            pass
    else:
        _fail(
            f"未安装浏览器扩展（缺 {dst}）→ 插件长连接无法建立：\n"
            f"        修复：运行 pool.bat setup（会自动从 {src} 复制）"
        )

    # 本 Skill 自身完整性：入口脚本一旦被改坏（非 ASCII/行尾/括号），整个入口会静默失效
    try:
        import lint_bat  # type: ignore

        for bat in sorted(C.SKILL_ROOT.glob("*.bat")):
            probs = lint_bat.lint(bat)
            if probs:
                _fail(f"{bat.name} 静态检查不通过：{probs[0]}")
            else:
                C.ok(f"{bat.name} 静态检查通过（ASCII/CRLF/括号/标签）")
    except Exception as e:
        _warn(f"批处理静态检查跳过：{e}")

    missing = [
        name
        for name in ("pool.bat", "scripts/_common.py", "scripts/setup_pool.py", "patches/README.md", "docs/00-新手必读.md")
        if not (C.SKILL_ROOT / name).exists()
    ]
    if missing:
        _warn(f"Skill 文件不完整（缺 {missing}）→ 重新解压/更新 Skill 目录")
    else:
        C.ok("Skill 文件完整")


def main() -> int:
    ap = argparse.ArgumentParser(description="生图号池环境自检")
    ap.add_argument("--no-network", action="store_true", help="跳过联网检查（/v1/models）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果（便于程序/Agent 解析）")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    t0 = time.time()
    if args.json:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _run_all(p := C.Paths.discover(), args)
        import json as _json

        print(
            _json.dumps(
                {
                    "ok": not FAILED,
                    "failed": list(FAILED),
                    "warned": list(WARNED),
                    "fpb_root": str(p.fpb_root) if p.fpb_root else None,
                    "vb_root": str(p.vb_root) if p.vb_root else None,
                    "elapsed_seconds": round(time.time() - t0, 2),
                    "log": buf.getvalue().splitlines(),
                },
                ensure_ascii=False,
            )
        )
        return 1 if FAILED else 0

    return _run_all(C.Paths.discover(), args)


def _run_all(p: C.Paths, args: argparse.Namespace) -> int:
    t0 = time.time()
    C.title("生图号池 环境自检 (doctor)")
    C.log(f"  skill 目录：{C.SKILL_ROOT}")

    check_python()
    check_paths(p)
    check_patches(p)
    check_services(p, network=not args.no_network)
    check_virtualbrowser(p)
    check_pool(p)
    check_extension_bridge(p)
    check_runtime_extras(p)

    C.log("")
    C.log("=" * 72)
    if FAILED:
        C.log(f"  结果：{len(FAILED)} 项失败，{len(WARNED)} 项警告（耗时 {time.time() - t0:.1f}s）")
        for i, m in enumerate(FAILED, 1):
            C.log(f"    {i}. {m}")
        C.log("  排错手册：docs/07-troubleshooting.md")
        C.log("  一键修复环境：pool.bat setup")
    else:
        C.log(f"  结果：全部通过 ✅（{len(WARNED)} 项警告，耗时 {time.time() - t0:.1f}s）")
        if WARNED:
            for i, m in enumerate(WARNED, 1):
                C.log(f"    {i}. {m}")
        C.log("  下一步：pool.bat test        （端到端自检：真出一张图）")
    C.log("=" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
