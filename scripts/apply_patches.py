"""应用上游补丁（**纯 Python 实现，不需要装 git**）

为什么不用 git：小白机器上大概率没有 git，或者 `git apply` 因为换行符/空白差异失败。
这里实现一个最小可用的 unified diff 应用器：按「旧侧内容」在文件里定位，找到就替换，
找不到就报告是哪个文件、哪一行、期望看到什么（而不是丢一句 "patch failed"）。

用法
----
    python scripts/apply_patches.py                 # 自动定位并打全部补丁
    python scripts/apply_patches.py --check         # 只检查是否已打（不改文件）
    python scripts/apply_patches.py --dry-run       # 只显示将要做的修改
    python scripts/apply_patches.py --revert        # 还原（反打补丁）

退出码：0 成功 / 1 失败（含无法定位根目录、补丁冲突）
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# 补丁文件名 → 用哪个根目录（a/ b/ 前缀之后是相对该根的路径）
PATCH_ROOTS = {
    "01-virtualbrowser-api_server.patch": "vb",
    "02-fpbrowser2api.patch": "fpb",
}


@dataclass
class Hunk:
    old_start: int
    body: list[str] = field(default_factory=list)

    @property
    def added_lines(self) -> list[str]:
        """本补丁新增的行（以 + 开头）——判断「是否已经打过」最可靠的信号。"""
        return [ln[1:] for ln in self.body if ln[:1] == "+"]

    @property
    def removed_lines(self) -> list[str]:
        return [ln[1:] for ln in self.body if ln[:1] == "-"]

    @property
    def old_lines(self) -> list[str]:
        return [ln[1:] if ln else "" for ln in self.body if ln[:1] in (" ", "-")]

    @property
    def new_lines(self) -> list[str]:
        return [ln[1:] if ln else "" for ln in self.body if ln[:1] in (" ", "+")]


@dataclass
class PatchFile:
    path: str
    hunks: list[Hunk] = field(default_factory=list)


def parse_patch(text: str) -> list[PatchFile]:
    """解析 unified diff（只看 ---/+++/@@ 与正文行）。"""
    files: list[PatchFile] = []
    cur: PatchFile | None = None
    for raw in text.splitlines():
        if raw.startswith("--- "):
            cur = PatchFile(path="")
            files.append(cur)
        elif raw.startswith("+++ ") and cur is not None:
            cur.path = raw[4:].split("\t")[0].strip()
        elif raw.startswith("@@") and cur is not None:
            m = HUNK_RE.match(raw)
            if m:
                cur.hunks.append(Hunk(old_start=int(m.group(1))))
        elif cur is not None and cur.hunks and (raw[:1] in (" ", "+", "-") or raw == ""):
            cur.hunks[-1].body.append(raw)
    # 丢掉没有 hunk 的（例如只有文件头的情况）
    return [f for f in files if f.hunks]


def split_keep_eol(text: str) -> tuple[list[str], str]:
    """把文本切成行数组 + 行尾样式（'\\n' / '\\r\\n' / ''）。"""
    if "\r\n" in text:
        eol = "\r\n"
    elif "\n" in text:
        eol = "\n"
    else:
        eol = ""
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    return body.split("\n"), eol


def _find(lines: list[str], want: list[str], hint: int) -> int:
    """在 lines 中定位 want。优先从 hint 附近找，再全文搜索。返回下标，找不到为 -1。"""
    if not want:
        return -1
    n = len(want)
    start = max(0, min(hint, len(lines) - 1))
    for i in (range(start, len(lines)), range(0, start)):
        for j in i:
            if j + n <= len(lines) and lines[j : j + n] == want:
                return j
    return -1


def already_applied(original: str, hunks: list[Hunk], *, reverse: bool = False) -> bool:
    """判断补丁是否已经打过了（按「新增/删除行是否已全部存在」判断）。

    很多用户会重复运行 setup / apply_patches（这是预期用法），
    所以「已经打过」应该报告为跳过，而不是失败。
    """
    probes: list[str] = []
    for h in hunks:
        probes += h.removed_lines if reverse else h.added_lines
    probes = [p for p in probes if p.strip()]
    return bool(probes) and all(p in original for p in probes)


def apply_to_text(original: str, hunks: list[Hunk], *, reverse: bool = False) -> tuple[str, str]:
    """应用 hunks。返回 (新文本, 错误信息)；错误信息为空表示成功。"""
    lines, eol = split_keep_eol(original)
    trailing_nl = original.endswith(("\n", "\r"))
    if lines and lines[-1] == "" and trailing_nl:
        lines = lines[:-1]

    for idx, h in enumerate(hunks):
        src = h.new_lines if reverse else h.old_lines
        dst = h.old_lines if reverse else h.new_lines
        if not src:
            return "", f"第 {idx + 1} 个 hunk 没有可匹配的原文内容（补丁损坏？）"
        at = _find(lines, src, max(0, h.old_start - 1))
        if at < 0:
            preview = "\n".join("      | " + s for s in src[:4])
            return "", (
                f"第 {idx + 1} 个 hunk 在文件里找不到对应的原始内容"
                f"（期望在约第 {h.old_start} 行附近看到）：\n{preview}\n"
                "      可能原因：上游代码版本不同，或补丁已经打过了。"
            )
        lines[at : at + len(src)] = dst

    out = eol.join(lines)
    if trailing_nl:
        out += eol
    return out, ""


def resolve_roots(p: C.Paths) -> dict[str, Path]:
    """补丁根目录：VB 补丁作用于含 api_server 的仓库根；FPB 补丁作用于项目根。"""
    roots: dict[str, Path] = {}
    if p.vb_api_server:
        roots["vb"] = p.vb_api_server.parent
    elif p.vb_root:
        roots["vb"] = p.vb_root
    if p.fpb_root:
        roots["fpb"] = p.fpb_root
    return roots


def validate_patch(path: Path) -> list[str]:
    """校验补丁自身是否合法：每个 hunk 的行数与 @@ 头是否一致、是否含疑似凭据。

    手写过补丁的人很容易把 `@@ -271,4 +342,4 @@` 的行数写错：
    内置应用器不依赖行数（所以看不出来），但 `git apply` 会直接失败。
    """
    problems: list[str] = []
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    cur: dict | None = None

    def _check(c: dict) -> None:
        if c["old"] != c["oc"] or c["new"] != c["nc"]:
            problems.append(
                f"第 {c['line']} 行 hunk 头 {c['hdr'].strip()} 与实际行数不符"
                f"（头声明 old={c['oc']},new={c['nc']}；实际 old={c['old']},new={c['new']}）→ git apply 会报 patch does not apply"
            )

    for i, ln in enumerate(lines):
        if ln.startswith("--- ") or ln.startswith("+++ ") or ln.startswith("diff "):
            if cur:
                _check(cur)
                cur = None
            continue
        m = HUNK_RE.match(ln)
        if m:
            if cur:
                _check(cur)
            cur = {
                "line": i + 1,
                "hdr": ln,
                "oc": int(m.group(2) or 1),
                "nc": int(m.group(4) or 1),
                "old": 0,
                "new": 0,
            }
            continue
        if cur is None:
            continue
        if ln[:1] in ("-", "+"):
            if ln[:1] == "-":
                cur["old"] += 1
            else:
                cur["new"] += 1
        elif ln[:1] == " " or ln == "":
            # 空行只算上下文（文件末尾的换行不会产生额外部）
            if i < len(lines) - 1:
                cur["old"] += 1
                cur["new"] += 1
    if cur:
        _check(cur)

    # 凭据扫描：补丁不应携带任何真实密钥（只看内容，去掉 diff 的 +/-/空格 标记，
    # 否则 python 装饰器 `@app.get` 会被误判成邮箱）
    bodies = "\n".join(ln[1:] if ln[:1] in ("+", "-", " ") else ln for ln in lines)
    for name, rx in SECRET_PATTERNS:
        for m in rx.finditer(bodies):
            problems.append(f"补丁里出现了疑似{name}：{m.group(0)[:40]}…（请脱敏后再提交）")
    return problems


SECRET_PATTERNS = [
    ("API Key", re.compile(r"(?:sk|gho|ghp)_[A-Za-z0-9]{20,}")),
    ("网关密钥", re.compile(r"(?:mirrmart|sora2)_[A-Za-z0-9_]{6,}")),
    ("真实邮箱", re.compile(r"[A-Za-z0-9._%+\-]{2,}@(?!example\.com|users\.noreply\.github\.com)[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+\.[A-Za-z]{2,6}")),
]


def check_markers(p: C.Paths) -> list[tuple[str, bool]]:
    """用字符串标记快速判断补丁是否已打（doctor 也用这个）。"""
    from doctor import PATCH_MARKERS  # 延迟导入，避免循环

    out = []
    for kind, rel, marker, _desc in PATCH_MARKERS:
        base = p.vb_api_server.parent if kind == "vb" and p.vb_api_server else (p.vb_root or p.fpb_root)
        target = (base / rel) if base else None
        hit = False
        if target and target.exists():
            try:
                hit = marker in target.read_text(encoding="utf-8", errors="replace")
            except Exception:
                hit = False
        out.append((rel, hit))
    return out


def run(p: C.Paths, *, patch_dir: Path, reverse: bool = False, dry_run: bool = False, check_only: bool = False) -> int:
    roots = resolve_roots(p)
    if not roots:
        C.fail("没找到任何可用于打补丁的目录（FPBrowser2API / VirtualBrowser），先运行 pool.bat setup 或设置 FPB_ROOT/VB_ROOT")
        return 1

    patches = sorted(x for x in patch_dir.glob("*.patch"))
    if not patches:
        C.fail(f"补丁目录里没有 .patch 文件：{patch_dir}")
        return 1

    total_ok = total_fail = total_skip = 0
    for patch_path in patches:
        key = PATCH_ROOTS.get(patch_path.name, "")
        root = roots.get(key)
        C.log("")
        C.log(f"── {patch_path.name}  (根目录：{root})")
        if not root:
            C.warn(f"跳过：当前环境里没有对应目录（{key}）")
            total_skip += 1
            continue

        files = parse_patch(patch_path.read_text(encoding="utf-8", errors="replace"))
        for pf in files:
            rel = re.sub(r"^[ab]/", "", pf.path)
            target = root / rel
            if not target.exists():
                C.fail(f"{rel}  → 文件不存在（上游版本不同？）")
                total_fail += 1
                continue

            original = target.read_text(encoding="utf-8", errors="replace")

            if already_applied(original, pf.hunks, reverse=reverse):
                C.ok(f"{rel}  → 已{'还原' if reverse else '打过补丁'}")
                if check_only:
                    total_ok += 1
                else:
                    total_skip += 1
                continue

            if check_only:
                C.fail(f"{rel}  → 未打补丁")
                total_fail += 1
                continue
                # 正向补丁的「新侧内容」应该已存在，反向则相反
                probe = pf.hunks[0].new_lines if not reverse else pf.hunks[0].old_lines
                done = bool(probe) and all(ln in original for ln in probe[:3] if ln.strip())
                (C.ok if done else C.fail)(f"{rel}  {'已是最新' if done else '未打补丁'}")
                total_ok += 1 if done else 0
                total_fail += 0 if done else 1
                continue

            if dry_run:
                C.info(f"{rel}  → 将应用 {len(pf.hunks)} 个 hunk（未写盘）")
                total_ok += 1
                continue

            new_text, err = apply_to_text(original, pf.hunks, reverse=reverse)
            if err:
                C.fail(f"{rel}  {err}")
                total_fail += 1
                continue

            if new_text == original:
                C.warn(f"{rel}  → 内容无变化（可能已经打过）")
                total_skip += 1
                continue

            backup = target.with_suffix(target.suffix + ".prepatch.bak")
            if not backup.exists():
                backup.write_bytes(target.read_bytes())
            target.write_text(new_text, encoding="utf-8", newline="")
            C.ok(f"{rel}  → {'还原' if reverse else '应用'}了 {len(pf.hunks)} 个 hunk（备份：{backup.name}）")
            total_ok += 1

    C.log("")
    C.log("-" * 68)
    if check_only:
        C.log(f"  检查完成：已打 {total_ok}，未打 {total_fail}")
        return 0 if total_fail == 0 else 1
    C.log(f"  完成：成功 {total_ok}，跳过 {total_skip}，失败 {total_fail}")
    if total_fail:
        C.info("失败时按 patches/README.md 的「手动改法速查表」逐条对照修改即可。")
    return 0 if total_fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="应用/还原上游补丁（无需 git）")
    ap.add_argument("--patch-dir", default=str(C.SKILL_ROOT / "patches"), help="补丁目录")
    ap.add_argument("--check", action="store_true", help="只检查补丁是否已打")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要做的修改")
    ap.add_argument("--revert", action="store_true", help="反打补丁（还原上游代码）")
    ap.add_argument("--validate", action="store_true", help="只校验补丁文件自身（hunk 行数 + 凭据扫描）")
    args = ap.parse_args()
    C.ensure_stdout_encoding()
    patch_dir = Path(args.patch_dir)
    if args.validate:
        C.title("校验补丁文件")
        bad = 0
        for f in sorted(patch_dir.glob("*.patch")):
            probs = validate_patch(f)
            if probs:
                bad += len(probs)
                C.fail(f"{f.name}")
                for x in probs:
                    C.info(f"    · {x}")
            else:
                C.ok(f"{f.name}（hunk 行数正确、未发现凭据）")
        return 1 if bad else 0
    C.title("应用上游补丁")
    p = C.Paths.discover()
    C.log(p.report())
    return run(p, patch_dir=Path(args.patch_dir), reverse=args.revert, dry_run=args.dry_run, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
