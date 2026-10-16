#!/usr/bin/env python3
"""敏感信息扫描（提交前 / CI 必跑）

号池类项目最容易犯的错：把卡密、token、密钥、内网地址写进文档或脚本里，
一旦推到公开仓库就等于泄露。本脚本把「人工肉眼检查」变成一条命令。

覆盖
----
- 卡密行（邮箱----密码----2FA----token）
- JWT（access_token）
- 常见 API Key 形态（sk_/gho_/ghp_/vendor 前缀）
- 私钥（-----BEGIN ... PRIVATE KEY-----）
- 内网 / 本机地址（192.168.x.x、10.x.x.x、172.16-31.x.x）
- 明文密码赋值（password = "..."）
- 提交前禁止入库的文件名（accounts.txt、*.db、*.log、.env）

用法
----
    python scripts/scan_secrets.py                 # 扫描仓库（自动跳过 .git/二进制/依赖目录）
    python scripts/scan_secrets.py --path some.txt # 只扫某个文件
    python scripts/scan_secrets.py --quiet         # 只在发现问题时输出

退出码：0 干净 / 1 发现问题
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "output", "logs", "scratch", ".ruff_cache", ".pytest_cache"}
SKIP_SUFFIX = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".pdf", ".zip", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo", ".db", ".sqlite", ".woff", ".woff2", ".ttf",
}
# 允许出现的「示例型 / 文档占位」内容
ALLOW = (
    re.compile(r"example\.com"),
    re.compile(r"DEMO_|REPLACE_ME|YOUR_|<your|xxx+", re.I),
    re.compile(r"\.prepatch\.bak"),
    re.compile(r"fpb-bridge-secret"),                 # 上游默认的演示 bridge token
    re.compile(r'fpb-bridge-"\s*\+|fpb-bridge-"$'),    # 代码里现场生成的 token 前缀
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("卡密行（邮箱----密码----2FA----token）", re.compile(r"[\w.+-]+@[\w.-]+----[^\s-][^\s]*----[A-Z2-7]{8,}----eyJ")),
    ("JWT / access_token", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}")),
    ("OpenAI/GitHub Token", re.compile(r"\b(?:sk|gho|ghp|ghs|xoxb)-?[A-Za-z0-9_\-]{20,}\b")),
    ("厂商密钥", re.compile(r"\b(?:mirrmart|sora2)_[a-z0-9_]*\d{6,}\b")),
    ("生成的网关密钥", re.compile(r"\bfpb-[0-9a-f]{12,}\b")),
    ("私钥文件", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("内网/本机地址", re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
    ("明文凭据赋值", re.compile(r"""(?:password|passwd|pwd|secret|access_token)\s*[:=]\s*["'][^"'\s]{8,}["']""", re.I)),
] or []

FORBIDDEN_FILES = [re.compile(r"^accounts.*\.txt$"), re.compile(r"\.(db|sqlite|log|env)$"), re.compile(r"^proxies\.txt$")]


def allowed(fragment: str) -> bool:
    return any(rx.search(fragment) for rx in ALLOW)


def scan_text(path: Path, text: str) -> list[str]:
    """扫一个文件。文档（.md）里允许出现 192.168.x.x 这种示例地址；代码里不允许。"""
    is_doc = path.suffix.lower() in (".md", ".rst", ".txt")
    hits: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        if "scan-secrets:allow" in line:  # 测试夹具等有意保留的行，显式豁免
            continue
        for name, rx in PATTERNS:
            if is_doc and name == "内网/本机地址":
                continue  # 文档里的示例地址是有意保留的
            m = rx.search(line)
            if not m or allowed(line):
                continue
            frag = m.group(0)
            hits.append(f"{path}:{i}  [{name}]  {frag[:60]}")
    return hits


def scan_file(path: Path) -> list[str]:
    if path.suffix.lower() in SKIP_SUFFIX:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    return scan_text(path, text)


def scan_forbidden_names(root: Path) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name.endswith(".example.txt"):
            continue
        if any(rx.match(p.name) for rx in FORBIDDEN_FILES):
            hits.append(f"{p}  [不该入库的文件]  {p.name}")
    return hits


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in SKIP_DIRS for part in p.parts):
            yield p


def main() -> int:
    ap = argparse.ArgumentParser(description="敏感信息扫描")
    ap.add_argument("--path", default="", help="只扫指定文件")
    ap.add_argument("--root", default="", help="扫描根目录（默认本仓库）")
    ap.add_argument("--quiet", action="store_true", help="只在发现问题时输出")
    args = ap.parse_args()

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    targets = [Path(args.path)] if args.path else list(iter_files(root))

    hits: list[str] = []
    for f in targets:
        hits += scan_file(f)
    if not args.path:
        hits += scan_forbidden_names(root)

    if hits:
        print(f"发现 {len(hits)} 处疑似敏感信息：")
        for h in hits:
            print("  ✗", h)
        print("\n处理：脱敏（换成 example.com / DEMO_ / YOUR_...）或把文件加进 .gitignore。")
        return 1

    if not args.quiet:
        print(f"✅ 已扫描 {len(targets)} 个文件，未发现敏感信息。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
