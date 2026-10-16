"""双击即用的中文菜单（pool.bat 不带参数时进入）

小白不需要记任何命令：双击 `pool.bat` → 看菜单 → 按数字。
每个选项都会先做前置检查，缺什么就告诉你先做什么。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

SKILL = C.SKILL_ROOT
PY = sys.executable

MENU = [
    ("1", "启动号池服务", "start_all.py", "让两端服务跑起来（后台无窗口，随时可关本窗口）"),
    ("2", "看看现在的状态", "status_all.py", "服务/窗口/token/最近任务的看板"),
    ("3", "全面体检", "doctor.py", "9 大类检查，缺什么都会告诉你怎么修"),
    ("4", "导入卡密（建号池）", "import_chatgpt_tokens.py", "把 accounts.txt 里的账号导进号池"),
    ("5", "预热窗口池", "warmup_windows.py", "新号池必做一次：让插件长连接与目标站就绪"),
    ("6", "出一张图", "gen_image.py", "输入提示词，直接得到图片"),
    ("7", "批量出图", "batch_gen.py", "从一个提示词文件里批量生成"),
    ("8", "端到端自检", "selftest.py", "真出一张图，确认整条链路可用"),
    ("9", "一键搭建/修复环境", "setup_pool.py", "自动装依赖/打补丁/建空间/起服务"),
    ("t", "同步窗口与任务池", "sync_vb_pool.py", "VirtualBrowser 里改了环境后重新同步"),
    ("v", "服务日志", "@logs", "看最近的日志，排查失败原因"),
    ("r", "清场重置", "reset_pool.py", "窗口卡死/状态混乱时用（保留账号）"),
    ("s", "停止服务", "stop_all.py", "关闭指纹窗口并停止服务"),
    ("i", "安装到 AI 助手 skills 目录", "install_skill.py", "装好后在任何会话里都能调用本 Skill"),
    ("q", "退出", "@quit", ""),
]


def run_script(script: str, extra: list[str], interactive: bool = True) -> int:
    path = SKILL / "scripts" / script
    cmd = [PY, str(path)] + extra
    try:
        return subprocess.call(cmd, cwd=str(SKILL))
    except KeyboardInterrupt:
        C.warn("已中断")
        return 130


def tail_logs() -> None:
    d = C.Paths.discover().log_dir
    if not d.exists():
        C.warn("还没有日志目录（服务没启动过？）")
        return
    print()
    C.log(f"  日志目录：{d}")
    for f in sorted(d.glob("*.log")):
        print()
        C.log(f"── {f.name} " + "─" * 40)
        C.log(C.tail_file(f, lines=15) or "  (空)")


def show_menu() -> None:
    p = C.Paths.discover()
    vb = "运行中" if C.tcp_listening(p.vb_port) else "未运行"
    fpb = "运行中" if C.tcp_listening(p.fpb_port) else "未运行"
    C.log("")
    C.log("=" * 68)
    C.log("  ChatGPT 生图号池 · 控制台")
    C.log(f"  VirtualBrowser API: {vb}   FPBrowser2API: {fpb}")
    C.log(f"  目录: {p.fpb_root or '(未找到)'}  |  {p.vb_root or '(未找到)'}")
    C.log("=" * 68)
    for key, name, _, note in MENU:
        C.log(f"   [{key}] {name:22s} {note}")
    C.log("")


def main() -> int:
    C.ensure_stdout_encoding()
    if not sys.stdin.isatty():
        # 非交互（被脚本调用）时直接打印命令列表，避免卡住
        C.log("当前不是交互式终端，无法显示菜单。可用命令：")
        C.log("  pool.bat start|stop|status|doctor|warm|sync|gen|batch|import|setup|test|reset|install-skill|logs")
        return 0
    while True:
        show_menu()
        try:
            choice = input("  请输入选项编号（回车=刷新，q=退出）：").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in ("", "\r", "\n"):
            continue
        if choice == "q":
            return 0
        item = next((m for m in MENU if m[0] == choice), None)
        if not item:
            C.warn("没有这个选项，重新输入")
            continue
        key, name, script, _ = item

        if script == "@quit":
            return 0
        if script == "@logs":
            tail_logs()
            input("\n  回车继续 ...")
            continue

        # --- 需要交互输入的选项 ---
        extra: list[str] = []
        if script == "gen_image.py":
            C.log("")
            prompt = input("  提示词（直接回车取消）：").strip()
            if not prompt:
                continue
            out = input("  保存到（回车=output/时间戳.png）：").strip()
            ratio = input("  画幅（回车=1:1，可选 16:9/9:16/4:3/3:4）：").strip()
            extra = [prompt]
            if out:
                extra += ["-o", out]
            if ratio:
                extra += ["--ratio", ratio]
        elif script == "batch_gen.py":
            C.log("")
            f = input("  提示词文件路径（回车取消）：").strip()
            if not f:
                continue
            c = input("  并发数（回车=3）：").strip()
            n = input("  输出目录（回车=output）：").strip()
            extra = [f]
            extra += ["--concurrency", c] if c else []
            extra += ["--outdir", n] if n else []
        elif script == "import_chatgpt_tokens.py":
            C.log("")
            f = input("  卡密文件路径（回车=accounts.txt）：").strip() or "accounts.txt"
            only = input("  先只导前几个验证？（回车=全部，输入数字=前 N 个）：").strip()
            extra = ["-f", f]
            if only.isdigit() and only:
                extra += ["--only", only]
            extra += ["--yes"]
        elif script == "warmup_windows.py":
            C.log("")
            C.info("新号池首次预热约 1–3 分钟/20 个窗口，中间会反复开关窗口，属正常现象。")
            keys = input("  只预热某些窗口 key（逗号分隔，回车=全部）：").strip()
            extra = ["--keys", keys] if keys else []
        elif script == "reset_pool.py":
            C.log("")
            C.warn("默认只清场不停账号；如需连窗口池绑定一起清空，请用命令行加 --purge-pool --yes")
        elif script == "install_skill.py":
            C.log("")
            C.info("装到 ~/.agents/skills/chatgpt-image-pool（如已存在会提示加 --force）")
        elif script in ("start_all.py", "stop_all.py", "status_all.py", "sync_vb_pool.py", "setup_pool.py", "selftest.py", "doctor.py"):
            C.log("")

        print()
        try:
            rc = run_script(script, extra)
        except Exception as e:
            C.fail(f"执行失败：{e!r}")
            rc = 1
        print()
        C.log(f"  ── 退出码：{rc} " + ("（成功）" if rc == 0 else "（失败，看上面的提示）"))
        try:
            input("  回车返回菜单 ...")
        except (EOFError, KeyboardInterrupt):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
