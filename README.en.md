<div align="center">

# ChatGPT Image Pool Kit

**Turn N ChatGPT accounts into one concurrent text-to-image production line.**
VirtualBrowser fingerprint browsers + FPBrowser2API scheduler + a batteries-included
toolkit of scripts and docs.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg)](#requirements)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg)](#requirements)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF.svg)](https://github.com/qiyuechen0929/chatgpt-image-pool/actions)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](pyproject.toml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Docs](https://img.shields.io/badge/docs-English-blue.svg)](README.en.md)

**[中文文档](README.md)** · **[Quickstart](docs/QUICKSTART.md)** · **[Troubleshooting](docs/07-troubleshooting.md)**

</div>

![A real generation from this kit's pool (1.3 MB PNG, preview compressed)](docs/images/demo-output.jpg)

---

## What it is

You have dozens of ChatGPT accounts and a fingerprint browser, but you still open each
window and click "generate" by hand. This kit turns that into a pipeline:

```bat
pool.bat gen "a shiba inu wearing an astronaut helmet, flat illustration" --ratio 1:1 -o out/shiba.png
pool.bat batch prompts.txt --concurrency 6        :: 6 accounts in parallel, auto-distributed
```

Full chain: **cards → environments → window pool → warmup → concurrent generation → auto-download**.
Every failure tells you how to fix it.

| Without | With |
|---|---|
| Open windows, log in, click generate manually | One command; the pool picks a free account |
| "Which account still has quota?" — check one by one | `pool.bat status` shows everything |
| Importing 20 accounts takes half an hour | `pool.bat import accounts.txt --yes` — about 3 minutes |
| Errors are a bare stack trace | Errors ship with a "→ do this next" hint |
| 10 pitfalls during installation | `pool.bat setup` — one idempotent command |

---

## Highlights

**For beginners**
- **One-command setup** — `pool.bat setup` does venv → deps → patches → config → extension → services → space/task-type → self-check (9 idempotent steps)
- **Double-click to use** — running `pool.bat` with no arguments opens a numbered menu; no commands to memorize
- **[Newbie guide (Chinese)](docs/00-%E6%96%B0%E6%89%8B%E5%BF%85%E8%AF%BB.md)** — glossary, "what you should see" per step, 12 common traps, acceptance checklist
- **Actionable errors** — expired token, extension not connected, quota exhausted, port in use… each mapped to a concrete fix

**For engineers**
- **No hardcoded paths** — auto-discovery plus `FPB_ROOT` / `VB_ROOT` / `VB_API_URL` / `FPB_API_URL` / `POOL_PYTHON` overrides
- **End-to-end self-test** — `pool.bat test` really generates an image and validates magic bytes + size (not "it looks installed")
- **Patch without git** — built-in unified-diff applier: `pool.bat patch [--check|--revert|--validate]`
- **Machine readable** — `doctor` / `test` / `gen` / `batch` all support `--json` (failures include a `hint`), ready for your own system or an AI agent
- **Windowless background services** — `DETACHED_PROCESS` + log rotation; closing the console can't kill your pool
- **Token-aware result download** — internal estuary links are fetched with the window's token and validated as real images (no more "0 KB success")
- **Self-healing** — auto-retry with a hardened prompt when the model only replies with text; auto-cleanup of stale processes/locks when a window fails to start
- **Reproducible patches** — verified by "upstream file → apply patch → byte-compare with the running files"

---

## Quick start

### Path A — complete beginner

> Requires Windows + [VirtualBrowser](https://virtualbrowser.cc) client + [Python 3.11/3.12](https://www.python.org/downloads/) (**check "Add to PATH"**)

```bat
pool.bat setup                                  :: does everything (idempotent)
pool.bat import accounts.txt --yes              :: cards: email----password----2fa----access_token
pool.bat warm                                   :: warm up the window pool (once per pool)
pool.bat test                                   :: end-to-end check, generates a real image
pool.bat gen "a shiba inu astronaut, flat illustration" -o out/shiba.png
```

### Path B — step by step

See **[docs/QUICKSTART.md](docs/QUICKSTART.md)** (Chinese, ~30 minutes, includes manual install and patching).

### Path C — let your AI agent do it

```bat
pool.bat install-skill        :: installs into ~/.agents/skills/chatgpt-image-pool
```

Then just ask, in any session: *"use chatgpt-image-pool to build an image pool"* or
*"use chatgpt-image-pool to generate an image of a cyberpunk street"*.
`SKILL.md` teaches the agent the decision tree (`doctor --json` → act → `test --json`).

---

## Measured results

| Metric | Measured (single machine / 20 accounts / 16 GB RAM) |
|---|---|
| Build pool (import 20 cards + bind pool) | ≈ 3 min |
| Warm up 20 windows (first time) | ≈ 5 min (never needed again) |
| Single image | 25–90 s (free accounts vary) |
| 6-way concurrency | **6/6 success, 83 s total** |
| `pool.bat setup` re-run | ≈ 12 s (idempotent) |
| Self-check coverage | `doctor` 31 checks + `test` real generation |

---

## Architecture

```
                        ┌───────────────────────────────────────┐
 your app / CLI  ─────► │  FPBrowser2API        127.0.0.1:8002  │
 POST /v1/videos        │  · OpenAI-compatible  /v1/videos      │
                        │  · task queue / window pool / limits  │
                        │  · extension bridge  /api/extension/ws│
                        └───────┬───────────────────────┬───────┘
                                │ HTTP                  │ WebSocket (persistent)
                                ▼                       ▼
                ┌───────────────────────────┐  ┌────────────────────────────┐
                │ VirtualBrowser local API   │  │ Browser extension (1/window)│
                │ 127.0.0.1:9000            │  │ · calls APIs in page context│
                │ · /api/launchBrowser →CDP │  │ · reports progress + result │
                └───────────┬───────────────┘  └────────────────────────────┘
                            │ launch + CDP
                            ▼
                ┌───────────────────────────────────────────┐
                │ Fingerprint windows 1..N (own profile + proxy)
                │  · each caches its account's access_token  │
                │  · after warmup, reconnects automatically  │
                └───────────────────────────────────────────┘
```

**What happens on one generation**

1. You `POST /v1/videos {"model":"gpt-image2-1k","prompt":"..."}`
2. The scheduler picks a window by quota / concurrency / error-cooldown
3. `VirtualBrowser /api/launchBrowser` starts that window and returns its CDP port
4. A "bridge config page" is opened to hand `space_id / window_key / bridge_url` to the
   extension, then CDP is **disconnected** (lowers automation fingerprints)
5. The extension uses **that window's long token** inside the real page context, streaming
   progress and the result URL back
6. The result is persisted; `/v1/videos/{id}` returns `image_url`, and this kit's scripts
   download it with the proper token

---

## Command reference

| Command | Purpose | When |
|---|---|---|
| `pool.bat` | Numbered menu (double-click friendly) | You don't want to memorize commands |
| `pool.bat setup` | **One-command install/repair** (9 idempotent steps) | First time / environment looks wrong |
| `pool.bat test` | **End-to-end self-test** (really generates) | After install/config changes |
| `pool.bat doctor` | 30+ environment checks (`--json` for scripts) | First thing when something breaks |
| `pool.bat status` | Dashboard: services / windows / quota / token expiry / cooldown | Daily |
| `pool.bat start` / `stop` | Windowless background service control | Daily |
| `pool.bat import accounts.txt --yes` | Import cards (DB backed up, idempotent) | Add accounts / refresh tokens |
| `pool.bat warm` | Warm up pool (`--keys 6,16` to retry only failures) | Once per new pool |
| `pool.bat gen "prompt" -o a.png` | One image (auto-prompt-optimize, auto-pick, auto-download) | Daily |
| `pool.bat batch f.txt --concurrency 3` | Concurrent batch + JSON report | Bulk generation |
| `pool.bat batch --outdir out --retry-failed` | Retry only previous failures | Free accounts are flaky |
| `pool.bat sync` | Sync windows / prune dead / bind pool | After editing environments in the client |
| `pool.bat reset` | Clean reset (keeps accounts & tokens) | Messy state / stuck windows |
| `pool.bat logs --errors` | Tail logs (errors only) | Debugging |
| `pool.bat patch --check/--revert/--validate` | Patch check / revert / self-validate | After updating upstream |
| `pool.bat install-skill` | Install into your AI agent's skills dir | Agent usage |

Every command is a thin wrapper over `scripts/*.py`, so you can call them directly
(e.g. `python scripts/doctor.py --json`).

---

## Installation

### One command (recommended)

```bat
pool.bat setup
```

Steps: `1 environment → 2 locate/clone → 3 venv+deps → 4 patches → 5 config →
6 browser extension → 7 services → 8 pool skeleton → 9 self-check`.
Failures print `→ how to fix`; rerunning is safe.

Flags: `--skip-start`, `--no-clone`, `--vb-root <dir>`, `--fpb-root <dir>`, `--api-key <key>`.

### Manual

See [docs/02-install.md](docs/02-install.md) (Chinese).

### Requirements

| Item | Requirement |
|---|---|
| OS | **Windows 10 / 11** (VirtualBrowser client is Windows-only) |
| Python | **3.10+** (3.11 recommended) |
| VirtualBrowser | Client + its `api_server` (local API, no VIP needed) |
| Scheduler | [yang0/fpbrowser2api](https://github.com/yang0/fpbrowser2api) |
| RAM | ~300–500 MB per window; ≥ 16 GB for 20 windows |
| Cards | `email----password----2fa----access_token` (token enables the no-login path) |

### Updating

```bat
git pull
pool.bat patch      :: re-apply patches after upstream updates (already-applied hunks are skipped)
pool.bat setup      :: repair deps/config
pool.bat doctor     :: confirm all green
```

---

## Usage

```bat
:: one image
pool.bat gen "a shiba inu with headphones, flat illustration" --ratio 1:1 -o out/shiba.png
pool.bat gen --prompt-file prompt.txt --ratio 16:9 -o out/poster.png

:: concurrent batch (+ retry failures)
pool.bat batch examples/prompts.txt --outdir out --concurrency 6
pool.bat batch --outdir out --retry-failed

:: programmatic HTTP API
curl -X POST http://127.0.0.1:8002/v1/videos \
  -H "Authorization: Bearer <API_KEY>" -H "Content-Type: application/json" \
  -d '{"model":"gpt-image2-1k","prompt":"a shiba astronaut","aspect_ratio":"1:1"}'
:: then poll GET /v1/videos/{id} → status=completed → image_url
::   · do NOT pass duration/seconds for image models (server forces 4)
::   · image_url needs that window's token to download (otherwise 403)
```

Generation flags: `--ratio 1:1|16:9|9:16|4:3|3:4`, `--res 1k|2k|4k`,
`--style realistic|cyberpunk|anime|concept_art|oil_painting|product`,
`--raw-prompt`, `--retries N`, `--json`.

---

## FAQ (quick)

| Symptom | Fix |
|---|---|
| `浏览器插件未连接 window_key=N` | New pool wasn't warmed → `pool.bat warm` |
| `GPT pageFetch returned empty result` | Same cause (window never visited the target site) |
| `GPT access token not found` | Token expired → `pool.bat import accounts.txt --yes` |
| "Success" but the file is 0 KB / 33 bytes | Use `pool.bat gen` (token-aware download + format validation) |
| Window exits immediately (`exit_code=0`) | Patches already auto-clean and retry; otherwise `pool.bat stop` |
| Model only replies with text | Auto-retried with a hardened prompt; otherwise just re-run |
| Service died unexpectedly | `pool.bat stop` before installing packages |
| Messy state | `pool.bat reset` → `start` → `warm` |
| "Something's wrong but I don't know what" | `pool.bat doctor` (every failure carries a fix hint) |

Debugging order: `doctor` → `test` → `logs --errors` → `reset && start && warm`.

---

## Documentation

| Document | Content |
|---|---|
| [00 Newbie guide](docs/00-%E6%96%B0%E6%89%8B%E5%BF%85%E8%AF%BB.md) | Zero-to-running in 30 min (Chinese) |
| [QUICKSTART](docs/QUICKSTART.md) | From scratch to first image |
| [01 Architecture](docs/01-architecture.md) | Components, data flow, DB tables, task lifecycle |
| [02 Install](docs/02-install.md) / [03 Configure](docs/03-configure.md) | Upstream setup, patches, ports, API key, proxies |
| [04 Build pool](docs/04-build-pool.md) | Card injection vs browser login, warmup, quota & cooldown |
| [05 Daily use](docs/05-daily-use.md) | CLI / batch / HTTP API / result download |
| [06 Operations](docs/06-operations.md) | Start-stop, monitoring, scaling, proxy assignment, backup |
| [07 Troubleshooting](docs/07-troubleshooting.md) | Symptom → cause → fix → verification |
| [08 FAQ](docs/08-faq.md) | Principles / usage / ops / compliance |
| [patches/README](patches/README.md) | The 9 upstream changes, why each exists, manual steps |
| [SKILL.md](SKILL.md) | Agent skill spec (decision tree, JSON contract) |

> All documentation is currently written in Chinese. English docs contributions are very welcome —
> see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Security & compliance

**Never commit credentials.** The repo forbids it by automation:

```bat
python scripts/scan_secrets.py                      :: scans cards/JWTs/keys/private IPs (runs in CI)
python scripts/apply_patches.py --validate          :: blocks secrets smuggled inside patches
```

- Long-lived `access_token` storage is a **deliberate trade-off** for login-free generation:
  a deployed machine effectively holds those accounts — treat it as sensitive.
- Upstream admin defaults to **`admin/admin` on `0.0.0.0`** — change it and bind to `127.0.0.1`
  (see [SECURITY.md](SECURITY.md)).
- Too many accounts behind one egress IP risks correlated bans — prefer one proxy per window.

> **Disclaimer**: this project is for technical research and automation of accounts **you own or
> are authorized to use**. You are responsible for complying with the target site's Terms of
> Service and local law. Do not use it for abuse, paywall bypass, attacks or any illegal purpose.
> The authors accept no liability for account risk, bans, data loss or indirect damages.
> Full notice: **[DISCLAIMER.md](DISCLAIMER.md)**.

---

## Contributing

PRs, issues and discussions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md)
(it contains hard rules learned the hard way) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

```bat
python -m pytest tests/ -q            :: 43 offline tests
python -m ruff check scripts/ tests/  :: lint
python scripts/lint_bat.py            :: batch-file checks
python scripts/scan_secrets.py        :: credential scan
pool.bat doctor && pool.bat test      :: real end-to-end acceptance
```

## Credits

- [yang0/fpbrowser2api](https://github.com/yang0/fpbrowser2api) — scheduler gateway
- [yang0/VirtualBrowser](https://github.com/yang0/VirtualBrowser) — fingerprint browser local API
- [VirtualBrowser](https://virtualbrowser.cc) — fingerprint browser client

## License

[MIT](LICENSE) © 2026 qiyuechen0929

<div align="center">

If this saved you time, a ⭐ Star is the most direct way to support it.

</div>
