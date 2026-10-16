"""把本 Skill 安装到 Agent 的 skills 目录（一次安装，之后在任意会话里可用）

为什么需要：Skill 装在项目目录里只有自己看得到；装到 Agent 的全局 skills 目录后，
你（或你的 AI 助手）在任何目录、任何会话里说一句「用 chatgpt-image-pool 出一张图」
就能触发本 Skill。

用法
----
    python scripts/install_skill.py                       # 默认装到 ~/.agents/skills/chatgpt-image-pool
    python scripts/install_skill.py --name my-pool        # 换目录名
    python scripts/install_skill.py --link                # 用目录联接（改 Skill 立即生效，推荐）
    python scripts/install_skill.py --list                # 只显示会用到哪些目录
    python scripts/install_skill.py --target claude       # 装到 ~/.claude/skills/

安装完会打印：如何验证、如何在对话里触发、如何卸载。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

SKIP_DIRS = {"output", "logs", ".git", "__pycache__", "scratch"}
SKIP_SUFFIX = {".pyc", ".db", ".bak", ".out.log", ".err.log", ".prepatch.bak"}


def _skip_file(name: str) -> bool:
    """跳过敏感/临时文件：*.db、日志、临时输出（_x.txt）等。"""
    if Path(name).suffix in SKIP_SUFFIX or name.endswith(".bak"):
        return True
    if name.startswith("_") and Path(name).suffix in (".txt", ".json", ".log"):
        return True  # 脚本运行产生的临时文件
    return False


def candidate_targets() -> dict[str, Path]:
    home = Path.home()
    return {
        "agents": home / ".agents" / "skills",
        "claude": home / ".claude" / "skills",
        "codex": home / ".codex" / "skills",
        "cursor": home / ".cursor" / "skills",
    }


def copy_skill(src: Path, dst: Path) -> tuple[int, int]:
    files = dirs = 0
    for root, dirnames, filenames in os.walk(src):
        rel = Path(root).relative_to(src)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        dirs += 1
        for fn in filenames:
            if _skip_file(fn):
                continue
            shutil.copy2(Path(root) / fn, target_dir / fn)
            files += 1
    return files, dirs


def make_link(src: Path, dst: Path) -> bool:
    """用目录联接/符号链接指向源目录（改 Skill 无需重装）。"""
    try:
        if dst.exists():
            shutil.rmtree(dst)
        if C.IS_WINDOWS:
            rc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                capture_output=True,
                text=True,
                creationflags=0x08000000,
            )
            return rc.returncode == 0
        dst.symlink_to(src, target_is_directory=True)
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="把本 Skill 安装到 Agent 的 skills 目录")
    ap.add_argument("--name", default="chatgpt-image-pool", help="安装后的目录名（也是触发词之一）")
    ap.add_argument("--target", default="agents", choices=["agents", "claude", "codex", "cursor", "custom"], help="装到哪个 skills 根目录")
    ap.add_argument("--dir", default="", help="--target custom 时的目标根目录")
    ap.add_argument("--link", action="store_true", help="用目录联接代替复制（改本目录立即生效）")
    ap.add_argument("--force", action="store_true", help="已存在时覆盖")
    ap.add_argument("--uninstall", action="store_true", help="卸载（只删安装过去的副本）")
    ap.add_argument("--list", action="store_true", help="只列出候选目录")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    src = C.SKILL_ROOT
    roots = candidate_targets()
    if args.list:
        C.title("Agent skills 目录")
        for k, v in roots.items():
            C.log(f"  {k:8s} {v}  {'（存在）' if v.exists() else '（不存在，安装时会创建）'}")
        return 0

    if args.target == "custom":
        base = Path(args.dir) if args.dir else Path.cwd()
    else:
        base = roots[args.target]
    dst = base / args.name

    C.title("安装 Skill 到 Agent 目录")
    C.log(f"  源目录  : {src}")
    C.log(f"  目标    : {dst}")
    C.log(f"  方式    : {'目录联接（改源码立即生效）' if args.link else '复制（独立副本）'}")

    if args.uninstall:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
            C.ok("已卸载（本 Skill 目录不受影响）")
        else:
            C.warn("目标不存在，无需卸载")
        return 0

    if dst.exists() and not args.force:
        C.warn(f"目标已存在：{dst}")
        C.info("要覆盖请加 --force（例如更新了 Skill 内容后重新安装）")
        return 1

    base.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)

    if args.link and make_link(src, dst):
        C.ok("已创建目录联接")
    else:
        if args.link:
            C.warn("目录联接失败（可能需要权限），已改用复制方式")
        files, dirs = copy_skill(src, dst)
        C.ok(f"已复制 {files} 个文件 / {dirs} 个目录")

    skill_md = dst / "SKILL.md"
    C.log("")
    C.log(f"  校验：{'存在 ✅' if skill_md.exists() else '缺失 ❌'}  {skill_md}")
    C.log("")
    C.log("  怎么用（在你的 AI 助手里直接说）：")
    C.log(f"    “用 {args.name} 出一张图：一只柴犬宇航员”")
    C.log(f"    “用 {args.name} 搭一个生图号池”")
    C.log("")
    C.log("  卸载：")
    C.log(f"    python \"{src / 'scripts' / 'install_skill.py'}\" --uninstall")
    return 0 if skill_md.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
