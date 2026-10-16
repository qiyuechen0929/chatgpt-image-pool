"""错误自诊断（把报错翻译成「下一步做什么」）的测试。"""

from __future__ import annotations

import gen_image as G


def test_diagnose_plugin_not_connected() -> None:
    assert "warm" in G.diagnose("浏览器插件未连接：space_id='default' window_key='3'")


def test_diagnose_pagefetch_empty() -> None:
    assert "warm" in G.diagnose("GPT pageFetch returned empty result for /backend-api/f/conversation")


def test_diagnose_token_expired() -> None:
    assert "import" in G.diagnose("GPT access token not found")


def test_diagnose_quota() -> None:
    assert "额度" in G.diagnose("insufficient quota")


def test_diagnose_service_down() -> None:
    assert "start" in G.diagnose("Connection refused")


def test_diagnose_unknown_returns_empty() -> None:
    assert G.diagnose("某种从未见过的新错误") == ""


def test_harden_prompt_forbids_questions() -> None:
    out = G.harden_prompt("一只柴犬")
    assert "一只柴犬" in out
    assert "不要" in out


def test_is_clarify_failure() -> None:
    assert G.is_clarify_failure("已生成，你更喜欢哪种风格？")
    assert not G.is_clarify_failure("insufficient quota")


def test_looks_like_image_validates_magic_and_size() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 6000
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 6000
    assert G.looks_like_image(png)
    assert G.looks_like_image(jpg)
    assert not G.looks_like_image(b'{"detail":"File stream access denied"}')  # 33 字节错误 JSON
    assert not G.looks_like_image(b"\x89PNG" + b"\x00" * 100)  # 太小，认为是错误页


def test_first_image_url_fallbacks() -> None:
    assert G.first_image_url({"image_url": "a"}) == "a"
    assert G.first_image_url({"url": "b"}) == "b"
    assert G.first_image_url({"metadata": {"result_urls": ["c"]}}) == "c"
    assert G.first_image_url({}) == ""


def test_error_classes_carry_exit_codes() -> None:
    assert G.SubmitError("x").exit_code == G.EXIT_SUBMIT
    assert G.DownloadError("x").exit_code == G.EXIT_DOWNLOAD
    assert G.PoolError("x").exit_code == G.EXIT_TASK
