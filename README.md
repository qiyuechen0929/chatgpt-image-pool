<div align="center">

# ChatGPT 生图号池 · ChatGPT Image Pool Kit

**把 N 个 ChatGPT 账号变成一条可并发调用的出图产线。**
VirtualBrowser 指纹浏览器 + FPBrowser2API 调度网关 + 一套开箱即用的脚本与文档。

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg)](#环境要求)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg)](#环境要求)
[![CI](https://github.com/qiyuechen0929/chatgpt-image-pool/actions/workflows/ci.yml/badge.svg)](https://github.com/qiyuechen0929/chatgpt-image-pool/actions/workflows/ci.yml)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](pyproject.toml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Docs](https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87-blueviolet.svg)](docs/00-%E6%96%B0%E6%89%8B%E5%BF%85%E8%AF%BB.md)

**[零基础 30 分钟上手](docs/00-%E6%96%B0%E6%89%8B%E5%BF%85%E8%AF%BB.md)** ·
**[照着敲的快速开始](docs/QUICKSTART.md)** ·
**[排错手册](docs/07-troubleshooting.md)** ·
[English](README.en.md)

</div>

![一次真实出图（本仓库池子产出，720s→1.3MB PNG，预览已压缩）](docs/images/demo-output.jpg)

---

## 这是什么

你有几十个 ChatGPT 账号、一个指纹浏览器，却还在**一个个开窗口、一个个手动画图**？
本项目把这件事变成一条产线：

```bat
pool.bat gen "一只戴宇航头盔的柴犬，扁平插画风" --ratio 1:1 -o out/shiba.png
pool.bat batch prompts.txt --concurrency 6        :: 6 个账号并发，自动分配
```

它做的事：**卡密 → 建环境 → 绑定窗口池 → 预热 → 并发出图 → 自动下载原图**，
全流程自动化，并且**每一步失败都告诉你怎么修**。

| 没有它 | 有它 |
|---|---|
| 手动开窗口、手动登录、手动点画图 | 一条命令，自动挑空闲账号 |
| 想知道"哪个号还有额度"得一个个看 | `pool.bat status` 一屏看完 |
| 20 个号导入要半小时 | `pool.bat import accounts.txt --yes`，约 3 分钟 |
| 报错只有一句 stack trace | 报错自带「→ 下一步做什么」 |
| 装环境踩 10 个坑 | `pool.bat setup` 一条命令，幂等可重跑 |

---

## 亮点

**给完全的新手**
- **一键搭建**：`pool.bat setup` 自动完成「建 venv → 装依赖 → 打补丁 → 写配置 → 装浏览器扩展 → 起服务 → 建空间/任务类型 → 自检」（9 步幂等，可反复跑）
- **双击就能用**：不带参数运行 `pool.bat` 进入**中文数字菜单**，不用记任何命令
- **[《新手必读》](docs/00-%E6%96%B0%E6%89%8B%E5%BF%85%E8%AF%BB.md)**：术语扫盲 + 每步「应该看到什么」+ **12 个常见卡点** + 出师验收清单
- **出错会告诉你怎么办**：token 过期、插件未连接、额度用尽、端口占用……全部映射到具体修复动作

**给工程使用**
- **零硬编码路径**：自动探测安装位置；`FPB_ROOT` / `VB_ROOT` / `VB_API_URL` / `FPB_API_URL` / `POOL_PYTHON` 可覆盖
- **端到端自检**：`pool.bat test` 真出一张图并校验图片魔数与体积（不是"看起来装好了"）
- **免 git 打补丁**：内置 unified-diff 应用器 `pool.bat patch`，支持 `--check` / `--revert` / `--validate`
- **机器可读**：`doctor` / `test` / `gen` / `batch` 全部支持 `--json`（失败时带 `hint`），方便接自己的系统或交给 AI Agent
- **后台无窗口服务**：`DETACHED_PROCESS` 启动 + 日志自动轮转，不会因为误关控制台而停服
- **结果图自动授权下载**：内部 estuary 链接用窗口 token 拉取并校验真实图片格式（避免「0 KB 成功」假象）
- **错误自愈**：模型「只回文字不画图」自动加固提示词重试；窗口启动失败自动清残留进程与锁文件重试
- **可复现的补丁**：`patches/*.patch` 用「上游原始文件 → 打补丁 → 与线上运行文件逐字节比对」验证过

---

## 60 秒上手

### 路径 A：完全新手（推荐）

> 前置：Windows + 装好 [VirtualBrowser 客户端](https://virtualbrowser.cc) + [Python 3.11/3.12](https://www.python.org/downloads/)（**勾选 Add to PATH**）

```bat
:: 1) 双击 pool.bat → 按 9（一键搭建），或直接：
pool.bat setup

:: 2) 把卡密粘进 accounts.txt（格式：邮箱----密码----2FA----access_token）
pool.bat import accounts.txt --yes

:: 3) 预热窗口池（新池必做一次，20 个号约 3–5 分钟）
pool.bat warm

:: 4) 端到端自检：真出一张图
pool.bat test

:: 5) 开始出图
pool.bat gen "一只戴宇航头盔的柴犬，扁平插画风" --ratio 1:1 -o out/shiba.png
```

每一步「应该看到什么」都写在 **[docs/00-新手必读.md](docs/00-%E6%96%B0%E6%89%8B%E5%BF%85%E8%AF%BB.md)**。

### 路径 B：有基础，想照步敲

见 **[docs/QUICKSTART.md](docs/QUICKSTART.md)**（约 30 分钟，含手动装上游组件与打补丁）。

### 路径 C：让 AI 助手替你干

```bat
pool.bat install-skill        :: 装到 ~/.agents/skills/chatgpt-image-pool
```

之后在任意 AI 会话里说：

- 「用 chatgpt-image-pool 帮我搭一个生图号池」
- 「用 chatgpt-image-pool 出一张图：赛博朋克雨夜街道」
- 「用 chatgpt-image-pool 看看号池状态，把有问题的窗口排查掉」

Agent 会按 `SKILL.md` 里的决策树工作（先 `doctor --json` 判断环境 → 执行 → `test --json` 验收）。

---

## 实测数据

| 指标 | 实测（单机 / 20 账号 / 16 GB 内存） |
|---|---|
| 建池（导入 20 卡密 + 绑定窗口池） | ≈ 3 分钟 |
| 预热 20 个窗口（首次） | ≈ 5 分钟（之后无需再预热） |
| 单张出图 | 25–90 s（免费号波动） |
| 6 并发批量 | **6/6 成功，总耗时 83 s** |
| 一键搭建（环境已就绪时） | ≈ 12 s（幂等复跑） |
| 自检覆盖 | `doctor` 30+ 项 + `test` 端到端出图 |

---

## 架构

```
                        ┌───────────────────────────────────────┐
 你的程序 / CLI   ────► │  FPBrowser2API        127.0.0.1:8002  │
 POST /v1/videos        │  · OpenAI 兼容接口  /v1/videos        │
                        │  · 任务队列 / 窗口池 / 并发控制       │
                        │  · 扩展 WebSocket 桥 /api/extension/ws│
                        └───────┬───────────────────────┬───────┘
                                │ HTTP                  │ WebSocket（长连接）
                                ▼                       ▼
                ┌───────────────────────────┐  ┌────────────────────────────┐
                │ VirtualBrowser 本地 API    │  │ 浏览器插件（每个窗口一个）  │
                │ 127.0.0.1:9000            │  │ · 在真实页面上下文里调接口  │
                │ · /api/launchBrowser →CDP │  │ · 上报进度 / 回传结果 URL   │
                └───────────┬───────────────┘  └────────────────────────────┘
                            │ 启动 + CDP
                            ▼
                ┌───────────────────────────────────────────┐
                │ 指纹窗口 1..N（各自独立 profile + 代理）    │
                │  · 窗口池里缓存该账号的 access_token        │
                │  · 首次预热后，之后每次启动自动重连插件      │
                └───────────────────────────────────────────┘
```

**一次出图发生了什么**

1. 你 `POST /v1/videos {"model":"gpt-image2-1k","prompt":"..."}`
2. 调度器按额度 / 并发 / 错误冷却，从窗口池挑一个窗口
3. `VirtualBrowser /api/launchBrowser` 拉起该窗口，拿到 CDP 调试端口
4. 打开「插件配置中转页」，把 `space_id / window_key / bridge_url` 交给扩展，随即**断开 CDP**（降低被识别为自动化的概率）
5. 扩展用**该窗口的长 token** 在真实页面上下文里出图，回传进度与结果
6. 结果写回数据库，`/v1/videos/{id}` 返回 `image_url`；本仓库脚本自动带 token 下载成 PNG

---

## 命令总表

| 命令 | 作用 | 什么时候用 |
|---|---|---|
| `pool.bat` | **双击菜单**（中文数字菜单） | 不想记命令 |
| `pool.bat setup` | **一键搭建/修复环境**（9 步幂等） | 第一次 / 环境不对劲 |
| `pool.bat test` | **端到端自检**：真出一张图 | 装完 / 改完配置 / 排障后 |
| `pool.bat doctor` | 环境体检（30+ 项，`--json` 可程序化） | 出问题第一时间 |
| `pool.bat status` | 状态看板（服务/窗口/额度/token 有效期/冷却） | 每天看一眼 |
| `pool.bat start` / `stop` | 后台无窗口启停两端服务 | 日常 |
| `pool.bat import accounts.txt --yes` | 导入卡密建池（自动备份 DB，幂等） | 加号 / token 过期 |
| `pool.bat warm` | 预热窗口池（`--keys 6,16` 只补失败） | 新池必做一次 |
| `pool.bat gen "提示词" -o a.png` | 出一张（自动扩写、自动选号、自动下载） | 日常 |
| `pool.bat gen --prompt-file p.txt` | 提示词含标点时用文件传入 | 中文长提示词 |
| `pool.bat batch f.txt --concurrency 3` | 并发批量 + JSON 报告 | 大量出图 |
| `pool.bat batch --outdir out --retry-failed` | **只重跑上次失败的** | 免费号偶发失败 |
| `pool.bat sync` | 窗口同步 / 清理失效 / 绑定任务池 | 在客户端里改了环境 |
| `pool.bat reset` | 清场重置（保留账号与 token） | 状态混乱 / 窗口卡死 |
| `pool.bat logs --errors` | 看日志（支持只过滤错误行） | 排查失败原因 |
| `pool.bat patch --check` / `--revert` / `--validate` | 补丁检查 / 还原 / 自检 | 升级上游代码后 |
| `pool.bat install-skill` | 装到 AI 助手 skills 目录 | 想让 Agent 直接用 |

所有命令底层是 `scripts/*.py`，可以单独调用（例如 `python scripts/doctor.py --json`）。

### 参数速查（出图）

| 参数 | 取值 | 说明 |
|---|---|---|
| `--ratio` | `1:1` `16:9` `9:16` `4:3` `3:4` | 画幅 |
| `--res` | `1k` `2k` `4k` | 分辨率层级 |
| `--style` | `realistic` `cyberpunk` `anime` `concept_art` `oil_painting` `product` | 提示词扩写风格 |
| `--raw-prompt` | — | 不扩写，原样提交 |
| `--retries N` | 默认 2 | 模型只回文字时的加固重试次数 |
| `--json` | — | 机器可读输出 |

---

## 安装

### 一键（推荐）

```bat
pool.bat setup
```

它会依次完成 9 件事，并在结尾打印 `✅` 汇总与「下一步」：

```
1 环境体检   2 定位/克隆代码   3 建 venv 装依赖   4 打补丁
5 写配置     6 装浏览器扩展    7 后台起服务       8 建号池骨架   9 自检
```

- 任何一步失败都会给出 `→ 怎么修`，修完**再跑一次同样命令**即可（幂等）。
- 常用开关：`--skip-start`（只装环境）、`--no-clone`（不自动克隆）、`--vb-root` / `--fpb-root`（指定目录）。

### 手动

见 **[docs/02-install.md](docs/02-install.md)**（含上游仓库、依赖、补丁、扩展注册、跨机部署）。

### 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | **Windows 10 / 11**（VirtualBrowser 客户端只有 Windows 版） |
| Python | **3.10+**（推荐 3.11；脚本与上游依赖按 3.11 验证） |
| VirtualBrowser | 客户端（[virtualbrowser.cc](https://virtualbrowser.cc) / [vbbrowser.com](https://www.vbbrowser.com/)）+ 其 `api_server`（本地 API，免 VIP） |
| 调度网关 | [yang0/fpbrowser2api](https://github.com/yang0/fpbrowser2api) |
| 内存 | 每窗口约 300–500 MB；20 窗口建议 ≥ 16 GB |
| 磁盘 | 环境 + 缓存约 3–5 GB（不含出图产物） |
| 卡密 | 格式 `邮箱----密码----2FA----access_token`（有 token 才能走免登录路线） |

### 升级

```bat
git pull
pool.bat patch          :: 上游代码更新后重新打补丁（已打过的会自动跳过）
pool.bat setup          :: 补依赖 / 补配置 / 复核环境
pool.bat doctor         :: 确认全绿
```

---

## 使用

### 单张出图

```bat
pool.bat gen "一只戴耳机的柴犬，扁平插画风" --ratio 1:1 -o out/shiba.png
pool.bat gen "产品图：银色机械键盘，白色背景" --res 2k --style product -o out/kb.png
pool.bat gen --prompt-file prompt.txt --ratio 16:9 -o out/poster.png
```

### 批量并发

```bat
pool.bat batch examples/prompts.txt --outdir out --concurrency 6
```

产出 `out/001_<时间戳>.png` … 与 `out/_batch_report.json`（逐条明细、耗时、失败原因）。
失败项可以一键补跑：`pool.bat batch --outdir out --retry-failed`。

### 用自己的系统调用（HTTP API）

```bash
# 1) 取 API Key（后台可见，或读数据库）
#    sqlite3 data/fpbrowser.db "select api_key from system_config where id=1"

# 2) 提交
curl -X POST http://127.0.0.1:8002/v1/videos \
  -H "Authorization: Bearer <API_KEY>" -H "Content-Type: application/json" \
  -d '{"model":"gpt-image2-1k","prompt":"一只柴犬宇航员","aspect_ratio":"1:1"}'

# 3) 轮询 GET /v1/videos/{id} → status=completed → image_url
#    ⚠️ 图片模型经 /v1/videos 提交时不要传 duration/seconds（服务端自动置 4；若传必须=4）
#    ⚠️ image_url 是内部 estuary 链接，下载需要该窗口的 token（否则 403）
```

细节见 [docs/05-daily-use.md](docs/05-daily-use.md#c-http-api对接自己的系统)。

### 扩容 / 换号 / 代理

```bat
:: 加号（幂等，环境不会重建；自动备份数据库）
pool.bat import accounts_new.txt --yes

:: token 到期后只更新 token
pool.bat import accounts.txt --no-create-envs --yes

:: 一窗口一出口 IP（proxies.txt 按行对应卡密顺序）
pool.bat import accounts.txt --proxy-file proxies.txt --yes
```

---

## 常见问题快查

| 现象 | 一句话解决 |
|---|---|
| `浏览器插件未连接：window_key=N` | 新池没预热 → `pool.bat warm` |
| `GPT pageFetch returned empty result` | 同上（窗口没访问过目标站） |
| `GPT access token not found` | token 过期 → `pool.bat import accounts.txt --yes` |
| 出图"成功"但文件 0 KB / 33 字节 | 用本仓库的 `pool.bat gen`（自动带 token 下载 + 校验格式） |
| 窗口启动后立刻退出（`exit_code=0`） | 补丁已自动清理残留并重试；仍失败先 `pool.bat stop` |
| 模型只回一段文字没画图 | 已自动加固提示词重试；仍失败就再跑一次 |
| 服务莫名停了 | 装包时先 `pool.bat stop`（避免运行中替换依赖） |
| 状态越跑越乱 | `pool.bat reset` → `start` → `warm` |
| 我不知道环境哪里不对 | `pool.bat doctor`（每项失败都带修复指引） |

完整排错手册：[docs/07-troubleshooting.md](docs/07-troubleshooting.md)
排错三部曲：`doctor` → `test` → `logs --errors`。

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [00-新手必读](docs/00-%E6%96%B0%E6%89%8B%E5%BF%85%E8%AF%BB.md) | **零基础 30 分钟上手**：术语、三条路径、每步验收、12 个卡点 |
| [QUICKSTART](docs/QUICKSTART.md) | 从零到第一张图（照着敲，含验证方式） |
| [01-架构](docs/01-architecture.md) | 组件职责、数据流、数据库表、任务生命周期 |
| [02-安装](docs/02-install.md) | 上游组件、依赖、补丁、扩展注册、跨机部署 |
| [03-配置](docs/03-configure.md) | 端口、API Key、扩展桥、代理、`setting.toml` 全解 |
| [04-建池](docs/04-build-pool.md) | 卡密直灌 vs 浏览器登录两条路、预热原理、额度与冷却 |
| [05-日常使用](docs/05-daily-use.md) | CLI / 批量 / HTTP API / 结果下载 / 模型清单 |
| [06-运维](docs/06-operations.md) | 启停、巡检、扩容、代理分配、备份迁移、调优 |
| [07-排错](docs/07-troubleshooting.md) | 症状 → 根因 → 处理 → 验证 |
| [08-FAQ](docs/08-faq.md) | 原理/使用/运维/合规 四类问答 |
| [patches/README](patches/README.md) | **9 处上游改动**逐条原因 + 手动改法 + 密钥处理说明 |
| [SKILL.md](SKILL.md) | 给 AI Agent 的技能说明（决策树、能力清单、`--json` 契约、交付约定） |

---

## 项目结构

```
chatgpt-image-pool/
├── pool.bat                     # 唯一入口：双击出菜单，带参数即命令
├── SKILL.md                     # AI Agent 技能说明（含决策树与交付约定）
├── README.md / README.en.md     # 中文 / English
├── docs/
│   ├── 00-新手必读.md            # ★ 零基础上手
│   ├── QUICKSTART.md            # 从零到出图
│   ├── 01-architecture.md ～ 08-faq.md
│   └── images/demo-output.jpg   # 真实出图预览
├── scripts/
│   ├── _common.py               # 路径/配置自动探测 + 共享工具
│   ├── setup_pool.py            # ★ 一键搭建（9 步幂等）
│   ├── selftest.py              # ★ 端到端自检（真出一张图）
│   ├── menu.py                  # ★ 双击菜单
│   ├── doctor.py                # 环境体检（30+ 项）
│   ├── apply_patches.py         # ★ 打/还原/校验补丁（不需要 git）
│   ├── start_all.py / stop_all.py / status_all.py / tail_logs.py / reset_pool.py
│   ├── import_chatgpt_tokens.py # 卡密导入（长 token 直灌）
│   ├── warmup_windows.py        # 窗口池预热
│   ├── sync_vb_pool.py          # 窗口同步 / 清理 / 绑定
│   ├── gen_image.py             # 单张出图（错误自诊断）
│   ├── batch_gen.py             # 并发批量（--retry-failed）
│   ├── scan_secrets.py          # 敏感信息扫描（CI 必跑）
│   ├── lint_bat.py              # 批处理静态检查（ASCII/CRLF/括号/标签）
│   └── install_skill.py         # 装到 AI 助手 skills 目录
├── patches/                     # 上游 9 处必要改动（含逐条原因）
├── examples/                    # accounts / proxies / prompts 示例
├── tests/                       # 43 个离线单元测试
└── .github/                     # CI + issue / PR 模板
```

---

## 安全与合规

**请不要把凭据提交进仓库。** 本仓库自带防线：

```bat
python scripts/scan_secrets.py      :: 扫描卡密/JWT/密钥/内网地址（CI 每次提交都跑）
python scripts/apply_patches.py --validate   :: 拦截"补丁里夹带密钥"
```

- 长期保存 `access_token` 是为了免登录出图的**有意取舍**：部署这台机器 ≈ 持有这些账号，请按敏感机器对待。
- 上游后台**默认 `admin/admin` 且监听 `0.0.0.0`** —— 请改密码并改成 `127.0.0.1`（见 [SECURITY.md](SECURITY.md)）。
- 一个出口 IP 上跑太多账号有联动风控风险，建议一窗口一独立代理。
- 详细安全边界与报告方式见 **[SECURITY.md](SECURITY.md)**。

> **免责声明**：本项目仅用于技术研究，以及对**你本人拥有或已获授权**的账号进行自动化。
> 使用者须自行遵守目标站点服务条款与所在地法律；不得用于批量滥用、绕过付费、攻击或任何违法用途。
> 作者不对账号风险、风控结果、数据丢失或任何间接损失负责。
> 完整使用须知见 **[DISCLAIMER.md](DISCLAIMER.md)**。

---

## 贡献

欢迎 PR / issue / 讨论。请先读 **[CONTRIBUTING.md](CONTRIBUTING.md)**（有几条硬性规范，都是踩过的坑）。
参与本项目即表示同意遵守 **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)**。

```bat
python -m pytest tests/ -q                 :: 43 个离线测试
python -m ruff check scripts/ tests/       :: 静态检查
python scripts/lint_bat.py                 :: 批处理检查（改了 .bat 必跑）
python scripts/scan_secrets.py             :: 凭据扫描（必跑）
pool.bat doctor && pool.bat test           :: 真实链路验收
```

## 致谢

- [yang0/fpbrowser2api](https://github.com/yang0/fpbrowser2api) —— 调度网关（任务队列 / 窗口池 / 扩展桥）
- [yang0/VirtualBrowser](https://github.com/yang0/VirtualBrowser) —— 指纹浏览器本地 API
- [VirtualBrowser](https://virtualbrowser.cc) —— 指纹浏览器客户端

## License

[MIT](LICENSE) © 2026 qiyuechen0929

<div align="center">

如果这个项目帮你省下了时间，请点一个 ⭐ Star —— 这是对开源最直接的鼓励。

</div>
