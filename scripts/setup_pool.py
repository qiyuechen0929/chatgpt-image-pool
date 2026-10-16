"""一键搭建号池（给小白用的安装向导）

把「装环境 → 建库 → 建空间 → 起服务」这一整条链路自动化，幂等可重复执行。
任何一步失败都会告诉你**接下来该做什么**，而不是丢一堆堆栈。

它会做 9 件事
-------------
1. 环境体检（Python 版本、venv、pip、git、网络）
2. 定位 / 克隆 FPBrowser2API 与 VirtualBrowser 两个目录
3. 建 venv 并安装依赖（失败自动换国内镜像重试）
4. 打上游补丁（内置补丁器，**不需要 git**）
5. 写 config/setting.toml（端口 / api_key / 插件长连接）
6. 把浏览器扩展装进 VirtualBrowser 的 extensions 目录
7. 后台启动两端服务并等待就绪
8. 自动创建 项目 / 浏览器 / 空间 / gpt_workflow 任务类型（号池骨架）
9. 汇总自检（doctor）与下一步

用法
----
    python scripts/setup_pool.py                 # 全自动（已存在的步骤自动跳过）
    python scripts/setup_pool.py --yes           # 不问任何问题
    python scripts/setup_pool.py --skip-start    # 只装环境，不起服务
    python scripts/setup_pool.py --vb-root D:\\VirtualBrowser --fpb-root D:\\fpbrowser2api
    python scripts/setup_pool.py --no-clone      # 目录缺失时不要尝试 git clone

退出码：0 全部就绪 / 1 有步骤失败（看末尾汇总）
"""

from __future__ import annotations

import argparse
import re
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

DEFAULT_FPB_REPO = "https://github.com/yang0/fpbrowser2api.git"
DEFAULT_VB_REPO = "https://github.com/yang0/VirtualBrowser.git"
PIP_MIRRORS = [
    "",  # 官方源
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
]


@dataclass
class Result:
    name: str
    status: str  # ok / skip / warn / fail
    detail: str = ""
    fixes: list[str] = field(default_factory=list)


class Setup:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.results: list[Result] = []
        self.p = C.Paths.discover()
        if args.fpb_root:
            self.p.fpb_root = Path(args.fpb_root)
        if args.vb_root:
            self.p.vb_root = Path(args.vb_root)
        self.python = Path(sys.executable)

    # ---------------- 输出 ----------------
    def step(self, name: str) -> None:
        C.log("")
        C.log(f"── {name} " + "─" * max(0, 62 - len(name)))

    def add(self, name: str, status: str, detail: str = "", fixes: list[str] | None = None) -> None:
        self.results.append(Result(name, status, detail, fixes or []))
        (C.ok if status == "ok" else C.warn if status in ("skip", "warn") else C.fail)(f"{name}：{detail}" if detail else name)
        for f in fixes or []:
            C.info(f"    → {f}")

    def shell(self, cmd: list[str], cwd: Path | None = None, timeout: float = 900.0) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=0x08000000 if C.IS_WINDOWS else 0,  # CREATE_NO_WINDOW
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except FileNotFoundError as e:
            return 127, f"找不到命令：{e}"
        except subprocess.TimeoutExpired:
            return 124, f"命令超时（>{timeout:.0f}s）"

    # ---------------- 1. 环境体检 ----------------
    def step_environment(self) -> None:
        self.step("1/9 环境体检")
        v = sys.version_info
        if v < (3, 10):
            self.add(
                "Python 版本",
                "fail",
                f"当前 {v.major}.{v.minor}，需要 3.10+",
                ["安装 Python 3.11/3.12（勾选 Add to PATH）后重跑：python scripts\\setup_pool.py"],
            )
        else:
            self.add("Python 版本", "ok", f"{v.major}.{v.minor}.{v.micro}（{sys.executable}）")

        if C.IS_WINDOWS:
            gv = sys.getwindowsversion()
            C.info(f"系统：Windows build {gv.build}")
        if shutil.which("git"):
            self.add("git", "ok", "已安装（可用 git 克隆/打补丁）")
        else:
            self.add(
                "git",
                "warn",
                "未安装（不装也能用：补丁走内置补丁器，目录需手动准备）",
                ["如需自动克隆仓库：安装 Git for Windows 后重跑"],
            )
        self.add("网络", "ok", "pip 安装依赖若失败会自动换国内镜像重试")

    # ---------------- 2. 定位目录 ----------------
    def _clone(self, repo: str, target: Path, label: str) -> bool:
        if not shutil.which("git"):
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        C.info(f"克隆 {label}：{repo} → {target}（首次较慢，请耐心等）")
        rc, out = self.shell(["git", "clone", "--depth", "1", repo, str(target)], timeout=1200)
        if rc != 0:
            C.warn(f"克隆失败：{out.strip().splitlines()[-1] if out.strip() else rc}")
            return False
        return True

    def step_locate(self) -> None:
        self.step("2/9 定位代码目录")

        # --- FPBrowser2API ---
        if self.p.fpb_root and (self.p.fpb_root / "main.py").exists():
            self.add("FPBrowser2API", "ok", str(self.p.fpb_root))
        elif self.args.no_clone:
            self.add(
                "FPBrowser2API",
                "fail",
                "未找到代码目录（已禁用自动克隆）",
                ["git clone " + self.args.fpb_repo + " D:\\fpbrowser2api，然后重跑 setup"],
            )
        else:
            target = Path(self.args.fpb_root) if self.args.fpb_root else Path("D:/fpbrowser2api")
            if self._clone(self.args.fpb_repo, target, "FPBrowser2API"):
                self.p.fpb_root = target
                self.add("FPBrowser2API", "ok", f"已克隆到 {target}")
            else:
                self.add(
                    "FPBrowser2API",
                    "fail",
                    "目录缺失且自动克隆失败",
                    [
                        f"手动执行：git clone {self.args.fpb_repo} {target}",
                        "或下载 zip 解压到该目录（见 docs/02-install.md）",
                        "然后重跑：python scripts\\setup_pool.py",
                    ],
                )

        # --- VirtualBrowser ---
        vb_ok = bool(self.p.vb_root and (self.p.vb_root / "VirtualBrowser.exe").exists())
        vb_src_ok = bool(self.p.vb_api_server)
        if vb_ok or vb_src_ok:
            extra = "" if vb_ok else "（只找到 api_server 源码，没找到客户端安装目录）"
            self.add("VirtualBrowser", "ok", f"{self.p.vb_root} {extra}")
        elif self.args.no_clone:
            self.add("VirtualBrowser", "fail", "未找到", ["先安装 VirtualBrowser 客户端（见 docs/02-install.md）"])
        else:
            target = Path(self.args.vb_root) if self.args.vb_root else Path("D:/VirtualBrowser")
            if self._clone(self.args.vb_repo, target, "VirtualBrowser"):
                self.p.vb_root = target
                self.add("VirtualBrowser", "ok", f"已克隆到 {target}")
            else:
                self.add(
                    "VirtualBrowser",
                    "fail",
                    "未找到 VirtualBrowser（客户端 + api_server 都需要）",
                    [
                        "① 安装 VirtualBrowser 客户端（安装包自带 api_server 目录）",
                        "② 或 git clone " + self.args.vb_repo,
                        "装好后重跑：python scripts\\setup_pool.py",
                    ],
                )

    # ---------------- 3. venv + 依赖 ----------------
    def _venv_python(self, root: Path) -> Path:
        return root / ".venv" / "Scripts" / "python.exe" if C.IS_WINDOWS else root / ".venv" / "bin" / "python"

    def _deps_installed(self, root: Path) -> bool:
        """用 requirements.txt 的指纹标记判断是否装过（比 import 探针准，且不会重复装）。"""
        req = root / "requirements.txt"
        if not req.exists():
            return True
        import hashlib

        h = hashlib.sha1(req.read_bytes()).hexdigest()[:12]
        return (root / ".venv" / f".deps-{h}").exists()

    def _mark_deps(self, root: Path) -> None:
        req = root / "requirements.txt"
        if not req.exists():
            return
        import hashlib

        try:
            h = hashlib.sha1(req.read_bytes()).hexdigest()[:12]
            (root / ".venv" / f".deps-{h}").write_text("ok\n", encoding="utf-8")
        except Exception:
            pass

    def _ensure_venv(self, root: Path, label: str) -> Result | None:
        """确保 venv 存在。返回 None 表示可以继续，否则返回失败结果。"""
        venv_py = self._venv_python(root)
        if venv_py.exists():
            return None
        C.info(f"创建 venv：{root / '.venv'}")
        rc, out = self.shell([str(self.python), "-m", "venv", str(root / ".venv")], timeout=600)
        if rc != 0 or not venv_py.exists():
            return Result(
                f"{label} venv",
                "fail",
                "创建失败：" + (out.strip().splitlines()[-1] if out.strip() else str(rc)),
                ["确认 Python 安装完整（含 venv 模块），或手动执行 python -m venv .venv"],
            )
        return None

    def _pip_install(self, venv_py: Path, args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
        """pip 安装（自动换国内镜像重试）。返回 (成功, 最后一行的错误)。"""
        last = ""
        for mirror in PIP_MIRRORS:
            cmd = [str(venv_py), "-m", "pip", "install", "-q", "--disable-pip-version-check"] + args
            if mirror:
                cmd += ["-i", mirror]
                C.info(f"用镜像重试：{mirror}")
            rc, out = self.shell(cmd, cwd=cwd, timeout=1800)
            if rc == 0:
                return True, ""
            last = out.strip().splitlines()[-1] if out.strip() else str(rc)
        return False, last

    def _ensure_venv_and_deps(self, root: Path | None, label: str, *, mode: str = "pinned") -> Result:
        """mode=pinned：按 requirements.txt 装（FPBrowser2API）；
        mode=imports：只保证核心包可导入（VirtualBrowser 随客户端发行，已自带的不要动）。"""
        if not root or not root.exists():
            return Result(f"{label} 依赖", "skip", "目录不存在，跳过")
        bad = self._ensure_venv(root, label)
        if bad:
            return bad
        venv_py = self._venv_python(root)
        req = root / "requirements.txt"

        if mode == "imports":
            if C.module_available(venv_py, "fastapi") and C.module_available(venv_py, "uvicorn"):
                return Result(f"{label} 依赖", "ok", "已满足（跳过，不动已有环境）")
            if not req.exists():
                return Result(
                    f"{label} 依赖",
                    "fail",
                    "核心依赖缺失且没有 requirements.txt",
                    [f"手动安装：{venv_py} -m pip install fastapi uvicorn[standard] playwright"],
                )
            ok, err = self._pip_install(venv_py, ["-r", str(req)], cwd=root)
            return Result(
                f"{label} 依赖",
                "ok" if ok else "fail",
                "安装完成" if ok else f"安装失败：{err}",
                [] if ok else [f"手动执行：{venv_py} -m pip install -r {req}"],
            )

        if not req.exists():
            return Result(f"{label} 依赖", "skip", "没有 requirements.txt，跳过")
        if C.module_available(venv_py, "fastapi") and self._deps_installed(root):
            return Result(f"{label} 依赖", "ok", "已安装（跳过重复安装）")

        ok, err = self._pip_install(venv_py, ["-r", str(req)], cwd=root)
        if ok:
            self._mark_deps(root)
            return Result(f"{label} 依赖", "ok", "安装完成")
        return Result(
            f"{label} 依赖",
            "fail",
            f"安装失败：{err}",
            [f"手动执行：{venv_py} -m pip install -r {req} -i https://pypi.tuna.tsinghua.edu.cn/simple"],
        )

    def step_venv(self) -> None:
        self.step("3/9 创建 venv 并安装依赖")
        # 依赖安装会替换 fastapi/uvicorn 等包：如果服务正在跑，可能把运行中的服务弄崩。
        # 所以先判断「是否需要装」，需要就先停服务。
        needs_install = []
        for label, root in (("FPBrowser2API", self.p.fpb_root), ("VirtualBrowser", self.p.vb_api_server)):
            if root and root.exists() and (root / "requirements.txt").exists():
                venv_py = self._venv_python(root)
                if not venv_py.exists() or not self._deps_installed(root) or not C.module_available(venv_py, "fastapi"):
                    needs_install.append(label)
        if needs_install and (C.tcp_listening(self.p.fpb_port) or C.tcp_listening(self.p.vb_port)):
            C.warn(f"{('、'.join(needs_install))} 需要安装依赖；为避免在服务运行时替换包导致服务崩溃，先停服务")
            try:
                import stop_all as S

                S.stop_services(self.p, False)
                time.sleep(2)
            except Exception as e:
                C.warn(f"停止服务失败（将继续尝试安装）：{e}")

        r = self._ensure_venv_and_deps(self.p.fpb_root, "FPBrowser2API", mode="pinned")
        self.add(r.name, r.status, r.detail, r.fixes)
        # 注意：VirtualBrowser 的依赖目录是 api_server（venv 建在 api_server/.venv）
        r = self._ensure_venv_and_deps(self.p.vb_api_server, "VirtualBrowser", mode="imports")
        self.add(r.name, r.status, r.detail, r.fixes)
        # playwright 是预热/开窗的必需依赖，单独确认（上游 requirements 里可能漏掉）
        for label, root in (("VirtualBrowser", self.p.vb_api_server), ("FPBrowser2API", self.p.fpb_root)):
            if not root:
                continue
            py = self._venv_python(root)
            if not py.exists():
                continue
            if C.module_available(py, "playwright"):
                continue
            C.info(f"为 {label} 补装 playwright（预热/自动化开窗需要）")
            done, _err = self._pip_install(py, ["playwright"])
            self.add(
                f"{label} playwright",
                "ok" if done else "warn",
                "已安装" if done else "安装失败（预热会报缺少 playwright，可手动 pip install playwright）",
            )

    # ---------------- 4. 补丁 ----------------
    def step_patches(self) -> None:
        self.step("4/9 打上游补丁")
        if not self.p.fpb_root:
            self.add("补丁", "skip", "FPBrowser2API 目录未知，跳过")
            return
        import apply_patches as AP

        rc = AP.run(self.p, patch_dir=C.SKILL_ROOT / "patches")
        self.add(
            "补丁（9 处改动）",
            "ok" if rc == 0 else "fail",
            "全部已应用" if rc == 0 else "有补丁未打上",
            [] if rc == 0 else ["按 patches/README.md 的「手动改法速查表」逐条改，或看上面的失败原因"],
        )

    # ---------------- 5. 配置 ----------------
    @staticmethod
    def _ensure_toml(text: str, section: str, key: str, value: str) -> tuple[str, bool]:
        """在 [section] 里确保 key = value（缺失则插入，存在则保留原值除非为空）。返回 (新文本, 是否改动)。"""
        lines = text.splitlines()
        sec_re = re.compile(r"^\[([^\]]+)\]\s*$")
        start = end = None
        for i, ln in enumerate(lines):
            m = sec_re.match(ln.strip())
            if m and m.group(1) == section:
                start = i
                for j in range(i + 1, len(lines)):
                    if sec_re.match(lines[j].strip()):
                        end = j
                        break
                end = end if end is not None else len(lines)
                break
        if start is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines += [f"[{section}]", f"{key} = {value}"]
            return "\n".join(lines) + "\n", True
        key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i in range(start + 1, end):
            if key_re.match(lines[i]):
                cur = lines[i].split("=", 1)[1].strip().strip('"')
                if cur == "" or cur in ("''", '""'):
                    lines[i] = f"{key} = {value}"
                    return "\n".join(lines) + "\n", True
                return text, False
        lines.insert(end, f"{key} = {value}")
        return "\n".join(lines) + "\n", True

    def step_config(self) -> None:
        self.step("5/9 写配置 config/setting.toml")
        root = self.p.fpb_root
        if not root:
            self.add("配置文件", "skip", "FPBrowser2API 目录未知，跳过")
            return
        cfg = root / "config" / "setting.toml"
        example = root / "config" / "setting_example.toml"
        if not cfg.exists():
            if example.exists():
                cfg.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(example, cfg)
                self.add("config/setting.toml", "ok", "从 setting_example.toml 生成")
            else:
                self.add("配置文件", "fail", "缺少 config/setting.toml（也没有 setting_example.toml）", ["确认代码目录完整（git clone 是否成功）"])
                return

        text = cfg.read_text(encoding="utf-8")
        changed = False
        port = self.p.fpb_port
        bridge_token = ""
        m = re.search(r"^\s*bridge_token\s*=\s*\"([^\"]*)\"", text, re.M)
        if m:
            bridge_token = m.group(1)
        if not bridge_token:
            bridge_token = "fpb-bridge-" + secrets.token_hex(8)

        for section, key, value in (
            ("server", "port", str(port)),
            ("global", "api_key", f'"{self.args.api_key}"' if self.args.api_key else f'"fpb-{secrets.token_hex(8)}"'),
            ("extension_executor", "enabled", "true"),
            ("extension_executor", "base_url", f'"127.0.0.1:{port}"'),
            ("extension_executor", "bridge_token", f'"{bridge_token}"'),
            ("extension_executor", "task_timeout_seconds", "1800"),
        ):
            text, did = self._ensure_toml(text, section, key, value)
            changed = changed or did

        if changed:
            backup = cfg.with_suffix(".toml.bak")
            if not backup.exists():
                backup.write_bytes(cfg.read_bytes())
            cfg.write_text(text, encoding="utf-8", newline="")
            self.add("config/setting.toml", "ok", f"已补齐端口/api_key/插件长连接（备份 {backup.name}）")
        else:
            self.add("config/setting.toml", "ok", "配置完整（未改动）")

        # 让 Paths 重新读配置
        self.p.fpb_api_url = f"http://127.0.0.1:{port}"

    # ---------------- 6. 浏览器扩展 ----------------
    def step_extension(self) -> None:
        self.step("6/9 安装浏览器扩展（插件长连接）")
        src = (self.p.fpb_root / "browser_extension") if self.p.fpb_root else None
        if not src or not src.exists():
            self.add("浏览器扩展", "skip", "源码里没有 browser_extension 目录", ["确认 FPBrowser2API 代码完整"])
            return
        if not self.p.vb_root or not (self.p.vb_root / "VirtualBrowser.exe").exists():
            self.add(
                "浏览器扩展",
                "warn",
                "未找到 VirtualBrowser 安装目录，无法自动安装",
                [
                    f"手动复制：{src}  →  <VirtualBrowser安装目录>\\extensions\\fp_browser_extension",
                    "复制后在 VirtualBrowser 里确认扩展已启用（能连上插件即为成功）",
                ],
            )
            return

        dst = self.p.vb_root / "extensions" / "fp_browser_extension"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and not self.args.force_extension:
            # 版本比较：源码更新就覆盖
            try:
                a = (src / "manifest.json").read_text(encoding="utf-8", errors="replace")
                b = (dst / "manifest.json").read_text(encoding="utf-8", errors="replace")
                va = re.search(r'"version"\s*:\s*"([^"]+)"', a)
                vb_ = re.search(r'"version"\s*:\s*"([^"]+)"', b)
                if va and vb_ and va.group(1) == vb_.group(1):
                    self.add("浏览器扩展", "ok", f"已安装且版本一致（{va.group(1)}）")
                    return
                C.info(f"版本不同（{vb_.group(1) if vb_ else '?'} → {va.group(1) if va else '?'}），覆盖更新")
            except Exception:
                pass
        try:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            self.add("浏览器扩展", "ok", f"已安装到 {dst}")
        except Exception as e:
            self.add("浏览器扩展", "fail", f"复制失败：{e}", [f"手动复制 {src} → {dst}"])

    # ---------------- 7. 启动服务 ----------------
    def step_start(self) -> None:
        self.step("7/9 启动两端服务")
        if self.args.skip_start:
            self.add("启动服务", "skip", "--skip-start 已指定")
            return
        rc, out = self.shell([str(self.python), str(C.SKILL_ROOT / "scripts" / "start_all.py"), "--wait", "90"], timeout=300)
        for line in out.splitlines():
            if "[OK]" in line or "[FAIL]" in line or "[WARN]" in line:
                C.info(line.strip())
        up = C.tcp_listening(self.p.vb_port) and C.tcp_listening(self.p.fpb_port)
        self.add(
            "启动服务",
            "ok" if up else "fail",
            "两端已就绪" if up else "有服务没起来",
            [] if up else ["看日志：pool.bat logs", "跑体检：pool.bat doctor"],
        )

    # ---------------- 8. 自动建池骨架 ----------------
    def step_provision(self) -> None:
        self.step("8/9 创建号池骨架（项目/浏览器/空间/任务类型）")
        if not C.tcp_listening(self.p.fpb_port):
            self.add("号池骨架", "skip", "FPBrowser2API 未运行，跳过后可重跑 setup")
            return
        try:
            token = C.fpb_admin_login(self.p, username=self.args.fpb_user, password=self.args.fpb_password)
        except SystemExit as e:
            self.add("后台登录", "fail", str(e).splitlines()[0], [ln.strip() for ln in str(e).splitlines()[2:4]])
            return

        base = self.p.fpb_api_url.rstrip("/")
        created: list[str] = []
        try:
            # --- 项目 ---
            projects = C.http_json(f"{base}/api/admin/projects", token=token, timeout=30).get("projects") or []
            proj = next((x for x in projects if x.get("name") == self.args.project_name), None)
            if not proj:
                rsp = C.http_json(f"{base}/api/admin/projects", {"name": self.args.project_name}, token=token, timeout=30)
                pid = rsp.get("project_id")
                created.append(f"项目 {self.args.project_name}(id={pid})")
            else:
                pid = proj.get("id")
            if not pid:
                raise RuntimeError("创建项目失败（没有返回 project_id）")

            # --- 浏览器（vendor=virtualbrowser）---
            browsers = C.http_json(f"{base}/api/admin/projects/{pid}/browsers", token=token, timeout=30).get("browsers") or []
            br = next((x for x in browsers if str(x.get("vendor", "")).lower() in ("virtualbrowser", "vb", "virtual")), None)
            if not br:
                rsp = C.http_json(
                    f"{base}/api/admin/browsers",
                    {
                        "project_id": pid,
                        "name": "VirtualBrowser-Local",
                        "lan_addr": self.p.vb_api_url,
                        "vendor": "virtualbrowser",
                        "access_key": "",
                        "browser_pool_limit": self.args.pool_limit,
                    },
                    token=token,
                    timeout=30,
                )
                bid = rsp.get("browser_id")
                created.append(f"浏览器 VirtualBrowser-Local(id={bid}, {self.p.vb_api_url})")
            else:
                bid = br.get("id")
            if not bid:
                raise RuntimeError("创建浏览器失败（没有返回 browser_id）")

            # --- 空间 ---
            spaces = C.http_json(f"{base}/api/admin/browsers/{bid}/spaces", token=token, timeout=30).get("spaces") or []
            sp = spaces[0] if spaces else None
            if not sp:
                rsp = C.http_json(
                    f"{base}/api/admin/spaces",
                    {"browser_id": bid, "name": self.args.space_name, "space_id": "default", "project_ids": None},
                    token=token,
                    timeout=30,
                )
                space_pk = rsp.get("space_pk")
                created.append(f"空间 {self.args.space_name}(id={space_pk})")
            else:
                space_pk = sp.get("id")
            if not space_pk:
                raise RuntimeError("创建空间失败")

            # --- gpt_workflow 任务类型 ---
            tts = C.http_json(f"{base}/api/admin/task-types?include_all=true", token=token, timeout=30).get("task_types") or []
            tt = next((x for x in tts if x.get("code") == "gpt_workflow"), None)
            if not tt:
                rsp = C.http_json(
                    f"{base}/api/admin/task-types",
                    {
                        "name": "GPT生图",
                        "code": "gpt_workflow",
                        "project_id": pid,
                        "concurrency": 3,
                        "total_concurrency": 100,
                        "create_task_handler": "gpt_workflow",
                        "refresh_quota_handler": "gpt_balance",
                        "timeout_seconds": 1800,
                    },
                    token=token,
                    timeout=30,
                )
                tt_id = rsp.get("id") or rsp.get("task_type_id")
                created.append(f"任务类型 gpt_workflow(id={tt_id})")
            else:
                tt_id = tt.get("id")

            detail = ("新建：" + "，".join(created)) if created else f"已存在（空间 id={space_pk}，任务类型 id={tt_id}）"
            self.add("号池骨架", "ok", detail)
        except Exception as e:
            self.add(
                "号池骨架",
                "fail",
                f"{e}",
                [f"也可以手动在后台建：{base} → 项目 → 新建（厂商选 VirtualBrowser，地址 {self.p.vb_api_url}）→ 新建空间"],
            )

    # ---------------- 9. 自检 ----------------
    def step_verify(self) -> None:
        self.step("9/9 自检（doctor）")
        rc, out = self.shell([str(self.python), str(C.SKILL_ROOT / "scripts" / "doctor.py"), "--no-network"], timeout=180)
        fails = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
        okc = out.count("[OK]")
        self.add("doctor 自检", "ok" if rc == 0 else "fail", f"{okc} 项通过，{len(fails)} 项失败")
        for ln in fails[:6]:
            C.info(ln)
        if fails:
            C.info("完整报告：pool.bat doctor")

    # ---------------- 汇总 ----------------
    def summary(self) -> int:
        C.log("")
        C.title("搭建结果")
        order = {"ok": 0, "skip": 1, "warn": 2, "fail": 3}
        for r in sorted(self.results, key=lambda x: order.get(x.status, 9)):
            icon = {"ok": "✅", "skip": "⏭", "warn": "⚠", "fail": "❌"}[r.status]
            C.log(f"  {icon} {r.name}：{r.detail}")
        fails = [r for r in self.results if r.status == "fail"]
        warns = [r for r in self.results if r.status == "warn"]
        C.log("")
        if fails:
            C.log(f"  有 {len(fails)} 项失败，逐条按上面的「→」提示处理后，**重复执行本命令**即可（幂等，不会重复建）。")
            return 1
        if warns:
            C.log(f"  {len(warns)} 项提醒（不影响启动，但建议处理）。")
        C.log("")
        C.log("  下一步（复制即用）：")
        C.log("    1) 把卡密粘进 accounts.txt（格式：邮箱----密码----2FA----access_token）")
        C.log("    2) pool.bat import accounts.txt --yes")
        C.log("    3) pool.bat warm")
        C.log("    4) pool.bat test")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="一键搭建 ChatGPT 生图号池")
    ap.add_argument("--fpb-root", default="", help="FPBrowser2API 目录（缺失时会尝试克隆到此路径）")
    ap.add_argument("--vb-root", default="", help="VirtualBrowser 安装目录")
    ap.add_argument("--fpb-repo", default=DEFAULT_FPB_REPO, help="FPBrowser2API 仓库地址")
    ap.add_argument("--vb-repo", default=DEFAULT_VB_REPO, help="VirtualBrowser 仓库地址")
    ap.add_argument("--no-clone", action="store_true", help="目录缺失时不要尝试 git clone")
    ap.add_argument("--skip-start", action="store_true", help="只装环境，不启动服务")
    ap.add_argument("--api-key", default="", help="指定公开 API Key（默认自动生成并写入 setting.toml）")
    ap.add_argument("--project-name", default="VirtualBrowser", help="后台项目名")
    ap.add_argument("--space-name", default="默认分组", help="空间名")
    ap.add_argument("--pool-limit", type=int, default=20, help="浏览器池上限")
    ap.add_argument("--fpb-user", default="", help="后台管理员账号（默认读 setting.toml）")
    ap.add_argument("--fpb-password", default="", help="后台管理员密码（默认读 setting.toml）")
    ap.add_argument("--force-extension", action="store_true", help="强制覆盖已安装的浏览器扩展")
    ap.add_argument("--yes", action="store_true", help="不询问（保留给脚本化调用）")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    C.title("ChatGPT 生图号池 · 一键搭建")
    C.log("  说明：本命令幂等，可反复执行；每一步都会告诉你失败原因和修复方法。")

    s = Setup(args)
    t0 = time.time()
    for fn in (
        s.step_environment,
        s.step_locate,
        s.step_venv,
        s.step_patches,
        s.step_config,
        s.step_extension,
        s.step_start,
        s.step_provision,
        s.step_verify,
    ):
        try:
            fn()
        except Exception as e:  # 单步异常不打断整体
            s.add(fn.__name__, "fail", f"异常：{e!r}")

    rc = s.summary()
    C.log(f"  耗时 {time.time() - t0:.1f}s")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
