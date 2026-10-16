"""公用配置与路径探测（供 skill 内所有脚本复用）

设计目标：**脚本里不写死任何绝对路径**，换一台机器/换一个安装目录也能跑。

解析优先级（高 → 低）
----------------------
1. 命令行参数（各脚本自己处理）
2. 环境变量：`FPB_ROOT` / `VB_API_URL` / `VB_ROOT` / `POOL_PYTHON`
3. 常见安装位置自动探测
4. 抛错并给出可操作的修复提示

对外主要接口
------------
`Paths.discover()`      -> Paths 实例（懒加载，带缓存）
`Paths.report()`        -> 人类可读的解析结果（doctor 用）
`http_json()`           -> 简单的 JSON HTTP 调用（带超时/错误提示）
`tcp_listening(port)`   -> 端口是否在监听
`read_setting_toml()`   -> 读取 FPBrowser2API 的 config/setting.toml
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

IS_WINDOWS = sys.platform.startswith("win")

# skill 根目录（本文件在 <skill>/scripts/_common.py）
SKILL_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def log(msg: str = "") -> None:
    print(msg, flush=True)


def info(msg: str) -> None:
    print(f"  {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}", flush=True)


def title(text: str, width: int = 72) -> None:
    log("=" * width)
    log(f"  {text}")
    log("=" * width)


def tcp_listening(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    """端口是否已被监听（用于判断服务是否已启动）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, int(port))) == 0


def http_json(
    url: str,
    payload: Any = None,
    *,
    token: str | None = None,
    timeout: float = 30.0,
    method: str | None = None,
) -> dict[str, Any]:
    """极简 JSON 请求。失败时抛 RuntimeError，消息里带 URL 与响应片段，便于排错。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if payload is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        snippet = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"{url} -> HTTP {e.code}: {snippet}") from e
    except Exception as e:  # 连接被拒 / 超时
        raise RuntimeError(f"{url} 请求失败：{e}") from e


def http_ok(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


# --------------------------------------------------------------------------
# 配置解析
# --------------------------------------------------------------------------
@dataclass
class Paths:
    fpb_root: Path | None = None      # FPBrowser2API 代码根目录
    vb_root: Path | None = None       # VirtualBrowser 安装目录（含 VirtualBrowser.exe）
    vb_api_url: str = "http://127.0.0.1:9000"
    fpb_api_url: str = "http://127.0.0.1:8002"
    python: Path | None = None        # 建议使用的 Python（FPBrowser2API 的 venv）
    notes: list[str] = field(default_factory=list)

    # ---- 派生路径 ----
    @property
    def fpb_db(self) -> Path | None:
        return (self.fpb_root / "data" / "fpbrowser.db") if self.fpb_root else None

    @property
    def fpb_python(self) -> Path:
        """启动 FPBrowser2API 用的 Python（优先项目 venv）。"""
        if self.fpb_root:
            for c in (self.fpb_root / ".venv" / "Scripts" / "python.exe", self.fpb_root / ".venv" / "bin" / "python"):
                if c.exists():
                    return c
        return self.python or Path(sys.executable)

    @property
    def vb_python(self) -> Path:
        """启动 VirtualBrowser 本地 API 用的 Python（优先它自己的 venv）。"""
        if self.vb_api_server:
            for c in (
                self.vb_api_server / ".venv" / "Scripts" / "python.exe",
                self.vb_api_server / ".venv" / "bin" / "python",
            ):
                if c.exists():
                    return c
        return self.python or Path(sys.executable)

    @property
    def log_dir(self) -> Path:
        d = (self.fpb_root / "logs") if self.fpb_root else (SKILL_ROOT / "logs")
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def fpb_settings(self) -> Path | None:
        return (self.fpb_root / "config" / "setting.toml") if self.fpb_root else None

    @property
    def vb_api_server(self) -> Path | None:
        """VirtualBrowser 本地 API 服务目录（core.py / server.py 所在）。"""
        for cand in (
            (self.vb_root / "api_server") if self.vb_root else None,
            self.vb_root,
        ):
            if cand and (cand / "server.py").exists():
                return cand
        return None

    @property
    def fpb_port(self) -> int:
        try:
            return int(urlparse(self.fpb_api_url).port or 8002)
        except Exception:
            return 8002

    @property
    def vb_port(self) -> int:
        try:
            return int(urlparse(self.vb_api_url).port or 9000)
        except Exception:
            return 9000

    # ---- 探测 ----
    @classmethod
    def discover(cls) -> Paths:
        p = cls()
        p.fpb_root = _find_fpb_root(p)
        p.vb_root = _find_vb_root(p)
        p.vb_api_url = os.environ.get("VB_API_URL", "").strip() or "http://127.0.0.1:9000"
        p.fpb_api_url = _resolve_fpb_api_url(p)
        p.python = _find_python(p)
        return p

    def report(self) -> str:
        rows = [
            ("FPBrowser2API 根目录", str(self.fpb_root) if self.fpb_root else "(未找到)"),
            ("VirtualBrowser 安装目录", str(self.vb_root) if self.vb_root else "(未找到)"),
            ("VirtualBrowser API 服务", str(self.vb_api_server) if self.vb_api_server else "(未找到)"),
            ("VirtualBrowser API 地址", self.vb_api_url),
            ("FPBrowser2API 地址", self.fpb_api_url),
            ("任务数据库", str(self.fpb_db) if self.fpb_db else "(未找到)"),
            ("Python(建议)", str(self.python) if self.python else "(未找到，用当前解释器)"),
        ]
        width = max(len(k) for k, _ in rows)
        out = [f"  {k.ljust(width)} : {v}" for k, v in rows]
        if self.notes:
            out.append("")
            out += [f"  注意：{n}" for n in self.notes]
        return "\n".join(out)

    def require_fpb(self) -> Path:
        if not self.fpb_root:
            raise SystemExit(
                "未找到 FPBrowser2API 代码目录。\n"
                "  修复：设置环境变量 FPB_ROOT 指向它，例如\n"
                "        set FPB_ROOT=D:\\fpbrowser2api\n"
                "  或按 docs/02-install.md 先完成安装。"
            )
        return self.fpb_root


def _candidate_roots(names: list[str]) -> list[Path]:
    """生成候选目录：环境变量、skill 同级目录、常见盘符。"""
    cands: list[Path] = []
    for name in names:
        env = os.environ.get(name, "").strip()
        if env:
            cands.append(Path(env))
    return cands


def _find_fpb_root(p: Paths) -> Path | None:
    cands = _candidate_roots(["FPB_ROOT"])
    # skill 的常见部署位置：与 fpbrowser2api 并列，或 skill 自己就在 fpbrowser2api 里
    cands += [
        SKILL_ROOT.parent / "fpbrowser2api",
        SKILL_ROOT / "fpbrowser2api",
        SKILL_ROOT.parent.parent,
        SKILL_ROOT,
    ]
    for drive in ("D:/", "C:/", "E:/"):
        cands.append(Path(drive) / "fpbrowser2api")
    cands.append(Path.home() / "fpbrowser2api")

    seen = set()
    for c in cands:
        try:
            c = c.resolve()
        except Exception:
            continue
        if c in seen:
            continue
        seen.add(c)
        if (c / "main.py").exists() and (c / "config" / "setting.toml").exists():
            return c
        if (c / "main.py").exists() and (c / "config" / "setting_example.toml").exists():
            p.notes.append(f"{c} 存在但没有 config/setting.toml，请从 setting_example.toml 复制一份")
            return c
    return None


def _find_vb_root(p: Paths) -> Path | None:
    cands = _candidate_roots(["VB_ROOT"])
    for drive in ("D:/", "C:/", "E:/"):
        cands.append(Path(drive) / "VirtualBrowser")
        cands.append(Path(drive) / "Program Files" / "VirtualBrowser")
    cands.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "VirtualBrowser")
    cands += [
        SKILL_ROOT.parent / "VirtualBrowser-src",
        SKILL_ROOT.parent / "VirtualBrowser",
        SKILL_ROOT / "VirtualBrowser-src",
    ]

    seen = set()
    for c in cands:
        if not str(c):
            continue
        try:
            c = c.resolve()
        except Exception:
            continue
        if c in seen or not c.exists():
            continue
        seen.add(c)
        # 安装目录：含 VirtualBrowser.exe；源码目录：含 api_server/server.py
        if (c / "VirtualBrowser.exe").exists() or (c / "api_server" / "server.py").exists():
            return c
    return None


def _resolve_fpb_api_url(p: Paths) -> str:
    env = os.environ.get("FPB_API_URL", "").strip()
    if env:
        return env.rstrip("/")
    port = 8002
    if p.fpb_settings and p.fpb_settings.exists():
        cfg = read_toml(p.fpb_settings)
        try:
            port = int(cfg.get("server", {}).get("port", 8002))
        except Exception:
            port = 8002
    return f"http://127.0.0.1:{port}"


def _find_python(p: Paths) -> Path | None:
    env = os.environ.get("POOL_PYTHON", "").strip()
    cands: list[Path] = [Path(env)] if env else []
    if p.fpb_root:
        cands += [
            p.fpb_root / ".venv" / "Scripts" / "python.exe",
            p.fpb_root / ".venv" / "bin" / "python",
            p.fpb_root / "venv" / "Scripts" / "python.exe",
        ]
    for c in cands:
        if str(c) and c.exists():
            return c
    return None


def read_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # py>=3.11

        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        pass
    try:
        import tomli  # type: ignore

        with open(path, "rb") as f:
            return tomli.load(f)
    except Exception:
        return {}


def read_setting_toml(p: Paths | None = None) -> dict[str, Any]:
    p = p or Paths.discover()
    if p.fpb_settings and p.fpb_settings.exists():
        return read_toml(p.fpb_settings)
    return {}


def sqlite_connect(db: Path | None):
    import sqlite3

    if not db or not db.exists():
        raise SystemExit(f"未找到数据库：{db}\n  修复：确认 FPBrowser2API 至少启动过一次。")
    conn = sqlite3.connect(str(db), timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_stdout_encoding() -> None:
    """让输出编码自适应：

    - 输出到**控制台**：跟随控制台代码页（中文 Windows 是 cp936），中文显示正确；
    - 输出被**重定向到文件/管道**（如 `pool.bat doctor > doctor.txt`）：改用 UTF-8，
      这样用任何编辑器打开都不乱码。
    两种情况都容忍个别无法编码的字符（errors="replace"）。
    """
    try:
        if sys.stdout.isatty():
            sys.stdout.reconfigure(errors="replace")
            sys.stderr.reconfigure(errors="replace")
        else:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def detect_pool_ids(conn) -> tuple[int | None, int | None]:
    """从数据库里自动识别「空间 pk」与「gpt_workflow 任务类型 id」。

    返回 (space_pk, task_type_id)，找不到则为 None。
    这样脚本在新环境不需要用户手填这两个 ID。
    """
    space_pk = None
    task_type_id = None
    try:
        row = conn.execute(
            """
            SELECT s.id AS space_pk
            FROM spaces s
            LEFT JOIN browsers b ON b.id = s.browser_id
            WHERE s.deleted = 0
            ORDER BY (CASE WHEN LOWER(COALESCE(b.vendor,'')) IN ('virtualbrowser','vb','virtual') THEN 0 ELSE 1 END), s.id
            LIMIT 1
            """
        ).fetchone()
        if row:
            space_pk = int(row["space_pk"])
    except Exception:
        pass

    try:
        row = conn.execute(
            "SELECT id FROM task_types WHERE code = 'gpt_workflow' AND deleted = 0 ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            task_type_id = int(row["id"])
    except Exception:
        pass
    return space_pk, task_type_id


def jwt_exp(token: str) -> int:
    """从 JWT 里取 exp（秒）。解析失败返回 0。"""
    import base64
    import json as _json

    try:
        part = str(token).split(".")[1]
        part += "=" * (-len(part) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(part.encode("ascii")).decode("utf-8", "replace"))
        return int(payload.get("exp") or 0)
    except Exception:
        return 0


# --------------------------------------------------------------------------
# 管理员凭据 / 公开 API Key（**不写死密码**，从 setting.toml 读，可用参数或环境变量覆盖）
# --------------------------------------------------------------------------
def admin_credentials(p: Paths | None = None, username: str = "", password: str = "") -> tuple[str, str]:
    """管理员账号密码。优先级：参数 > 环境变量 > setting.toml [global] > 内置默认。

    FPBrowser2API 的默认就是 admin/admin，且它会把自己设置的账号密码明文写在
    config/setting.toml 的 [global] 段里，所以这里能直接读到用户的真实配置，
    无需让用户手动输入。
    """
    p = p or Paths.discover()
    cfg = read_setting_toml(p)
    g = (cfg.get("global") or {}) if cfg else {}
    user = (username or os.environ.get("FPB_ADMIN_USERNAME") or str(g.get("admin_username") or "")).strip() or "admin"
    pwd = password or os.environ.get("FPB_ADMIN_PASSWORD") or str(g.get("admin_password") or "")
    return user, pwd or "admin"


def fpb_admin_login(
    p: Paths | None = None,
    *,
    api_url: str = "",
    username: str = "",
    password: str = "",
    timeout: float = 20.0,
) -> str:
    """登录 FPBrowser2API 后台，返回会话 token。失败时给出可操作的提示。"""
    p = p or Paths.discover()
    base = (api_url or p.fpb_api_url).rstrip("/")
    user, pwd = admin_credentials(p, username, password)
    try:
        rsp = http_json(f"{base}/api/admin/login", {"username": user, "password": pwd}, timeout=timeout)
    except RuntimeError as e:
        raise SystemExit(
            f"登录 FPBrowser2API 后台失败：{e}\n"
            f"  当前使用的账号：{user}\n"
            "  修复：① 确认服务已启动（pool.bat start）；\n"
            "        ② 若你改过后台密码，用 --fpb-password 传入，或设置环境变量 FPB_ADMIN_PASSWORD；\n"
            f"        ③ 也可以直接在 config/setting.toml 的 [global] 里核对 admin_username/admin_password。"
        ) from e
    token = str(rsp.get("token") or "")
    if not token:
        raise SystemExit(f"登录 FPBrowser2API 后台未返回 token：{rsp}")
    return token


def fpb_api_key(p: Paths | None = None, explicit: str = "") -> str:
    """公开 API Key（调 /v1/* 用）。优先级：参数 > 环境变量 > 数据库 > 上游默认值。"""
    p = p or Paths.discover()
    if explicit.strip():
        return explicit.strip()
    env = (os.environ.get("FPB_API_KEY") or "").strip()
    if env:
        return env
    try:
        conn = sqlite_connect(p.fpb_db)
        row = conn.execute("SELECT api_key FROM system_config WHERE id = 1").fetchone()
        conn.close()
        if row and row["api_key"]:
            return str(row["api_key"])
    except Exception:
        pass
    return "fpb123456"


def resolve_pool_targets(p: Paths, conn, space_pk: int = 0, task_type_id: int = 0) -> tuple[int, int]:
    """拿到号池的 (space_pk, task_type_id)，缺失时给出**新手也能照做**的指引。"""
    auto_space, auto_tt = detect_pool_ids(conn)
    sp = int(space_pk or auto_space or 0)
    tt = int(task_type_id or auto_tt or 0)
    if not sp:
        raise SystemExit(
            "数据库里还没有可用的「空间」，无法继续。\n"
            "  原因：号池需要一个 vendor=virtualbrowser 的空间来挂窗口。\n"
            "  最快修复：运行  pool.bat setup  （会自动建项目/浏览器/空间/任务类型）\n"
            "  手动方式：打开后台 " + p.fpb_api_url + "  项目 → 新建浏览器（厂商选 VirtualBrowser，\n"
            "            接口地址 http://127.0.0.1:9000）→ 新建空间。"
        )
    if not tt:
        raise SystemExit(
            "数据库里还没有 gpt_workflow 任务类型（GPT 生图）。\n"
            "  最快修复：运行  pool.bat setup\n"
            f"  手动方式：打开后台 {p.fpb_api_url} → 任务类型 → 新建（代码填 gpt_workflow）。"
        )
    return sp, tt


# --------------------------------------------------------------------------
# 等待 / 日志 / 杂项
# --------------------------------------------------------------------------
def wait_http(url: str, timeout: float = 60.0, interval: float = 1.5) -> bool:
    """轮询等待 URL 变为可访问。"""
    import time as _t

    deadline = _t.time() + max(3.0, timeout)
    while _t.time() < deadline:
        if http_ok(url, timeout=4.0):
            return True
        _t.sleep(interval)
    return http_ok(url, timeout=4.0)


def wait_port(port: int, timeout: float = 60.0, interval: float = 1.5) -> bool:
    import time as _t

    deadline = _t.time() + max(3.0, timeout)
    while _t.time() < deadline:
        if tcp_listening(port):
            return True
        _t.sleep(interval)
    return tcp_listening(port)


def rotate_log(path: Path, max_bytes: int = 3_000_000, keep_bytes: int = 1_000_000) -> None:
    """日志超过 max_bytes 时只保留尾部 keep_bytes（避免长跑占满磁盘）。"""
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        with open(path, "rb") as f:
            f.seek(-keep_bytes, os.SEEK_END)
            tail = f.read()
        with open(path, "wb") as f:
            f.write(b"...[log rotated]...\n" + tail)
    except Exception:
        pass


def tail_file(path: Path, lines: int = 30, max_chars: int = 1800) -> str:
    """取文件尾部若干行（给启动失败时自动展示日志用）。"""
    try:
        if not path.exists():
            return ""
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 32768))
            data = f.read()
        text = data.decode("utf-8", "replace")
        out = "\n".join(text.splitlines()[-lines:])
        return out[-max_chars:]
    except Exception:
        return ""


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def module_available(python: Path, module: str, timeout: float = 60.0) -> bool:
    """检查某个 Python 解释器里能否 import 指定模块（用 subprocess，不靠 shell 引号）。"""
    import subprocess

    try:
        kwargs: dict = {"capture_output": True, "timeout": timeout}
        if IS_WINDOWS:
            kwargs["creationflags"] = 0x08000000
        proc = subprocess.run([str(python), "-c", f"import {module}"], **kwargs)
        return proc.returncode == 0
    except Exception:
        return False


def require_playwright() -> str | None:
    """检查 playwright 是否可用。返回 None 表示可用，否则返回错误说明。"""
    try:
        import playwright  # noqa: F401

        return None
    except Exception:
        return (
            "缺少 playwright（预热/自动化开窗需要它）：\n"
            "  修复：<FPB_ROOT>\\.venv\\Scripts\\python.exe -m pip install playwright"
        )


def dependency_problem(err_log: Path) -> str:
    """从服务错误日志里识别最常见的「依赖没装」问题。"""
    text = tail_file(err_log, lines=60, max_chars=6000)
    m = __import__("re").search(r"ModuleNotFoundError: No module named '([^']+)'", text)
    if m:
        return f"缺依赖包 {m.group(1)!r} → 装依赖：pip install -r requirements.txt（详见 docs/02-install.md）"
    if "Address already in use" in text or "error while attempting to bind" in text:
        return "端口被占用 → 换端口或先关闭占用进程（pool.bat status 可看端口）"
    return ""
