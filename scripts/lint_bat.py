"""批处理文件静态检查（防的是「改一行 bat，整个入口静默失效」这类坑）

检查项（都是真实踩过的）
------------------------
1. **ASCII-only**：cmd 解析含非 ASCII 字节的 .bat 会错位吃字符，把下一行开头吃掉
   → 表现为 `'xxx' 不是内部或外部命令`，甚至整个脚本行为错乱
2. **CRLF 行尾**：混用 LF 会让 `if (...)` 多行块解析异常
3. **括号块内的 echo 不能含未转义的 `(` `)`**：一个多余的 `)` 会提前结束块，
   导致块后面的命令**无条件执行**（例如本该只在出错时 pause，结果每次都 pause）
4. **`goto :label` 必须有对应 `:label`**
5. **引号配对**（粗查）

用法：
    python scripts/lint_bat.py                 # 检查本 Skill 的 pool.bat
    python scripts/lint_bat.py --glob "*.bat"
    python scripts/lint_bat.py --path D:\\x\\y.bat

退出码：0 通过 / 1 有问题
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

BLOCK_OPEN = re.compile(r"^\s*(if|for|else|rem)?.*\(\s*$")


def lint(path: Path) -> list[str]:
    problems: list[str] = []
    raw = path.read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as e:
        text = raw.decode("utf-8", "replace")
        line_no = raw[: e.start].count(b"\n") + 1
        problems.append(f"含非 ASCII 字节（第 {line_no} 行附近）→ 中文提示请交给 Python 打印，.bat 保持纯 ASCII")
    nt = raw.count(b"\r\n")
    nl = raw.count(b"\n")
    if nt != nl:
        problems.append(f"行尾不一致：CRLF={nt} 但总行数={nl}（.bat 必须全部 CRLF）")

    lines = text.replace("\r\n", "\n").split("\n")
    labels = {ln.strip()[1:].split()[0] for ln in lines if ln.strip().startswith(":")} if any(
        ln.strip().startswith(":") for ln in lines
    ) else set()
    gotos: list[tuple[int, str]] = []
    inside_block = False
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if not s or s.startswith("rem ") or s == "rem":
            continue
        # 进入/离开多行括号块
        if s.endswith("(") and not s.startswith("echo"):
            inside_block = True
        if inside_block and s.startswith("echo"):
            body = s[4:]
            if "(" in body or ")" in body:
                problems.append(f"第 {i} 行：括号块内的 echo 含未转义括号 → 会提前结束 if 块，块后面的命令会无条件执行。请去掉括号或写成 ^( ^)。")
        if s == ")" or (s.endswith(")") and not s.startswith(("echo", "rem")) and "(" not in s[:-1]):
            inside_block = False
        m = re.match(r"^goto\s+:?([A-Za-z0-9_]+)", s, re.I)
        if m:
            gotos.append((i, m.group(1)))
        if s.count('"') % 2 == 1 and not s.startswith("rem"):
            problems.append(f"第 {i} 行：双引号没有配对 → {s[:50]}")

    for i, label in gotos:
        if label.lower() in ("eof", "end"):
            continue
        if label not in labels and label.lower() not in {x.lower() for x in labels}:
            problems.append(f"第 {i} 行：goto :{label} 找不到对应标签")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="批处理静态检查")
    ap.add_argument("--path", default="", help="检查指定文件")
    ap.add_argument("--glob", default="*.bat", help="检查哪些文件（默认本目录的 *.bat）")
    args = ap.parse_args()

    C.ensure_stdout_encoding()
    files = [Path(args.path)] if args.path else sorted(C.SKILL_ROOT.glob(args.glob))
    files = [f for f in files if f.exists()]
    if not files:
        C.warn("没有找到要检查的 .bat")
        return 0

    total = 0
    for f in files:
        problems = lint(f)
        total += len(problems)
        if problems:
            C.fail(f"{f.name}")
            for p in problems:
                C.info(f"    · {p}")
        else:
            C.ok(f"{f.name}（ASCII / CRLF / 括号 / 标签 / 引号 全部正常）")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
