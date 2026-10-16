"""补丁解析 / 应用 / 校验 的测试（含真实补丁的自检）。

这些测试保证「不需要 git 也能打补丁」这条路径始终可用：
- 解析：hunk 归属、行数
- 应用：正/反向、上下文定位、已打过判定
- 校验：hunk 行数与 @@ 头一致（git apply 会因此失败）、凭据扫描
"""

from __future__ import annotations

from pathlib import Path

import apply_patches as AP

SKILL_ROOT = Path(__file__).resolve().parent.parent
PATCHES = sorted((SKILL_ROOT / "patches").glob("*.patch"))

SIMPLE = """\
--- a/x.py
+++ b/x.py
@@ -1,4 +1,4 @@
 import os
-old = 1
+new = 1
 print(1)
 print(2)
@@ -10,3 +10,4 @@
 keep
+added
 tail
"""


def test_parse_patch_structure() -> None:
    files = AP.parse_patch(SIMPLE)
    assert len(files) == 1
    assert files[0].path == "b/x.py"
    assert len(files[0].hunks) == 2
    assert files[0].hunks[0].old_lines == ["import os", "old = 1", "print(1)", "print(2)"]
    assert files[0].hunks[0].new_lines == ["import os", "new = 1", "print(1)", "print(2)"]
    assert files[0].hunks[0].added_lines == ["new = 1"]
    assert files[0].hunks[0].removed_lines == ["old = 1"]


def test_apply_forward_and_reverse_roundtrip() -> None:
    original = "import os\nold = 1\nprint(1)\nprint(2)\n" + "\n" * 5 + "keep\ntail\n"
    files = AP.parse_patch(SIMPLE)
    applied, err = AP.apply_to_text(original, files[0].hunks)
    assert err == ""
    assert "new = 1" in applied and "old = 1" not in applied
    assert "keep\nadded\ntail" in applied

    reverted, err2 = AP.apply_to_text(applied, files[0].hunks, reverse=True)
    assert err2 == ""
    assert reverted == original


def test_apply_reports_mismatch_with_hint() -> None:
    _out, err = AP.apply_to_text("完全不同的内容\n", AP.parse_patch(SIMPLE)[0].hunks)
    assert err and "找不到" in err


def test_already_applied_detection() -> None:
    files = AP.parse_patch(SIMPLE)
    applied = "import os\nnew = 1\nprint(1)\nprint(2)\n" + "\n" * 5 + "keep\nadded\ntail\n"
    assert AP.already_applied(applied, files[0].hunks)
    assert not AP.already_applied("import os\nold = 1\n", files[0].hunks)


def test_split_keep_eol_preserves_crlf() -> None:
    lines, eol = AP.split_keep_eol("a\r\nb\r\n")
    assert lines == ["a", "b", ""]
    assert eol == "\r\n"
    assert AP.split_keep_eol("a\nb\n")[1] == "\n"


def test_find_prefers_index_near_hint() -> None:
    lines = ["x", "y", "y", "y"]
    assert AP._find(lines, ["y", "y"], 2) >= 1


def test_real_patches_exist_and_are_valid() -> None:
    """仓库里的补丁必须能通过自检（hunk 行数正确且不含凭据）。"""
    assert PATCHES, "patches/ 目录下没有补丁文件"
    for p in PATCHES:
        problems = AP.validate_patch(p)
        assert problems == [], f"{p.name} 自检失败：{problems}"


def test_validate_detects_bad_hunk_count(tmp_path: Path) -> None:
    bad = tmp_path / "bad.patch"
    bad.write_text("--- a/x.py\n+++ b/x.py\n@@ -1,9 +1,9 @@\n-a\n+b\n", encoding="utf-8", newline="")
    problems = AP.validate_patch(bad)
    assert any("行数不符" in x for x in problems)


def test_validate_detects_secret(tmp_path: Path) -> None:
    evil = tmp_path / "evil.patch"
    evil.write_text(
        '--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-key = "mirrmart_sora2_880315"\n+key = "ok"\n',  # scan-secrets:allow
        encoding="utf-8",
        newline="",
    )
    problems = AP.validate_patch(evil)
    assert any("凭据" in x or "密钥" in x for x in problems)


def test_validate_allows_demo_email_in_patch(tmp_path: Path) -> None:
    ok = tmp_path / "ok.patch"
    ok.write_text(
        '--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-old\n+mail = "demo_user01@example.com"\n',
        encoding="utf-8",
        newline="",
    )
    assert AP.validate_patch(ok) == []
