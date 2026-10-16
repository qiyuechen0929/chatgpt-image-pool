"""批处理静态检查 / 敏感信息扫描 / 公共工具 的测试。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import _common as C
import lint_bat
import scan_secrets
import setup_pool


# ---------------------------------------------------------------- lint_bat
def _write_bat(tmp_path: Path, text: str, *, crlf: bool = True) -> Path:
    p = tmp_path / "t.bat"
    data = text.replace("\n", "\r\n").encode("ascii") if crlf else text.encode("ascii")
    p.write_bytes(data)
    return p


def test_lint_bat_accepts_good_file(tmp_path: Path) -> None:
    good = "@echo off\r\nif errorlevel 1 (\r\n    echo no parens here\r\n    pause\r\n)\r\ngoto :end\r\n:end\r\nexit /b 0\r\n"
    assert lint_bat.lint(_write_bat(tmp_path, good)) == []


def test_lint_bat_detects_parens_inside_block(tmp_path: Path) -> None:
    bad = "@echo off\nif errorlevel 1 (\n    echo bad (paren)\n    pause\n)\n"
    problems = lint_bat.lint(_write_bat(tmp_path, bad))
    assert any("括号" in p for p in problems)


def test_lint_bat_detects_lf_only(tmp_path: Path) -> None:
    problems = lint_bat.lint(_write_bat(tmp_path, "@echo off\necho hi\n", crlf=False))
    assert any("行尾" in p for p in problems)


def test_lint_bat_detects_non_ascii(tmp_path: Path) -> None:
    p = tmp_path / "c.bat"
    p.write_bytes("@echo off\r\necho 中文提示\r\n".encode())
    assert any("非 ASCII" in x for x in lint_bat.lint(p))


def test_lint_bat_detects_missing_label(tmp_path: Path) -> None:
    problems = lint_bat.lint(_write_bat(tmp_path, "@echo off\ngoto :nowhere\nexit /b 0\n"))
    assert any("找不到对应标签" in p for p in problems)


def test_repo_pool_bat_passes_lint() -> None:
    root = Path(__file__).resolve().parent.parent
    for bat in root.glob("*.bat"):
        assert lint_bat.lint(bat) == [], f"{bat.name} 静态检查未通过"


# ------------------------------------------------------------ scan_secrets
def test_scan_secrets_flags_card_line(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    # scan-secrets:allow  （这行本身就是被测的“脏样本”）
    dirty = "user1@mail-domain.net----Passw0rd----JBSWY3DPEHPK3PXP----eyJhbGciOiJSUzI1NiIs.abcdefghijklmnopqrstuv"  # scan-secrets:allow
    f.write_text(dirty, encoding="utf-8")
    hits = scan_secrets.scan_text(f, dirty.replace("scan-secrets:allow", ""))
    assert hits


def test_scan_secrets_allows_placeholders(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    text = "demo_user01@example.com----Passw0rd!A----JBSWY3DPEHPK3PXP----eyJhbGciOi...DEMO_SIGNATURE_REPLACE_ME\n"
    f.write_text(text, encoding="utf-8")
    assert scan_secrets.scan_text(f, text) == []


def test_scan_secrets_allows_private_ip_in_docs_only(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    code = tmp_path / "c.py"
    line = 'base_url = "192.168.1.100:8002"\n'  # scan-secrets:allow
    doc.write_text(line, encoding="utf-8")
    code.write_text(line, encoding="utf-8")
    assert scan_secrets.scan_text(doc, line) == []
    assert scan_secrets.scan_text(code, line)


def test_scan_secrets_respects_allow_marker(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    line = 'key = "mirrmart_sora2_880315"  # scan-secrets:allow\n'
    f.write_text(line, encoding="utf-8")
    assert scan_secrets.scan_text(f, line) == []


def test_repo_is_clean() -> None:
    """仓库自身必须干净（CI 会跑，防止把凭据提交进来）。"""
    root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for f in scan_secrets.iter_files(root):
        hits += scan_secrets.scan_file(f)
    assert hits == [], f"仓库里发现疑似敏感信息：{hits}"


# --------------------------------------------------------------- _common
def _jwt(exp_offset: int = 3600) -> str:
    import base64

    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64({'exp': int(time.time()) + exp_offset})}.sig"


def test_jwt_exp_roundtrip() -> None:
    exp = C.jwt_exp(_jwt(3600))
    assert abs(exp - (int(time.time()) + 3600)) < 5
    assert C.jwt_exp("not-a-jwt") == 0
    assert C.jwt_exp("") == 0


def test_human_bytes() -> None:
    assert C.human_bytes(512) == "512 B"
    assert "KB" in C.human_bytes(2048)
    assert "MB" in C.human_bytes(3 * 1024 * 1024)


def test_tcp_listening_false_for_unused_port() -> None:
    assert C.tcp_listening(1) is False  # 保留端口，正常不会有人监听的权限


def test_detect_pool_ids_from_temp_db(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE spaces(id INTEGER PRIMARY KEY, browser_id INTEGER, deleted INTEGER DEFAULT 0);
        CREATE TABLE browsers(id INTEGER PRIMARY KEY, vendor TEXT);
        CREATE TABLE task_types(id INTEGER PRIMARY KEY, code TEXT, deleted INTEGER DEFAULT 0);
        INSERT INTO browsers(id, vendor) VALUES (7, 'virtualbrowser');
        INSERT INTO spaces(id, browser_id, deleted) VALUES (42, 7, 0);
        INSERT INTO task_types(id, code, deleted) VALUES (9, 'gpt_workflow', 0);
        """
    )
    conn.commit()
    space_pk, tt = C.detect_pool_ids(conn)
    conn.close()
    assert space_pk == 42
    assert tt == 9


def test_rotate_log_keeps_tail(tmp_path: Path) -> None:
    f = tmp_path / "big.log"
    f.write_bytes(b"x" * 20000 + b"TAIL")
    C.rotate_log(f, max_bytes=1000, keep_bytes=100)
    data = f.read_bytes()
    assert data.startswith(b"...[log rotated]...")
    assert data.endswith(b"TAIL")
    assert len(data) < 200


def test_tail_file(tmp_path: Path) -> None:
    f = tmp_path / "a.log"
    f.write_text("\n".join(f"line{i}" for i in range(50)), encoding="utf-8")
    tail = C.tail_file(f, lines=3)
    assert tail.splitlines() == ["line47", "line48", "line49"]


def test_admin_credentials_prefers_explicit_over_env(monkeypatch) -> None:
    monkeypatch.setenv("FPB_ADMIN_PASSWORD", "envpass")
    user, pwd = C.admin_credentials(None, "u1", "explicit")
    assert (user, pwd) == ("u1", "explicit")


# ------------------------------------------------------------ setup_pool
def test_ensure_toml_inserts_missing_key() -> None:
    text = '[server]\nport = 8002\n\n[global]\napi_key = "keep-me"\n'
    out, changed = setup_pool.Setup._ensure_toml(text, "extension_executor", "enabled", "true")
    assert changed
    assert "[extension_executor]" in out
    assert "enabled = true" in out
    assert 'api_key = "keep-me"' in out


def test_ensure_toml_keeps_existing_non_empty_value() -> None:
    text = '[extension_executor]\nbridge_token = "abc"\n'
    out, changed = setup_pool.Setup._ensure_toml(text, "extension_executor", "bridge_token", '"new"')
    assert not changed
    assert out == text


def test_ensure_toml_fills_empty_value() -> None:
    text = '[global]\napi_key = ""\n'
    out, changed = setup_pool.Setup._ensure_toml(text, "global", "api_key", '"filled"')
    assert changed and 'api_key = "filled"' in out


def test_ensure_toml_new_section_at_end() -> None:
    out, changed = setup_pool.Setup._ensure_toml("[a]\nx = 1\n", "b", "y", "2")
    assert changed
    assert out.rstrip().endswith("y = 2")
