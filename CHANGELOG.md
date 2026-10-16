# 更新记录

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，版本号语义化。

## [1.1.0] - 2026-10-16

首次公开发布：把一次真实落地（VirtualBrowser + FPBrowser2API + 20 个 ChatGPT 账号）
整理成可复用的脚本、文档与补丁。

### 一键上手（降低门槛）

- `pool.bat setup`（`scripts/setup_pool.py`）：**一键搭建/修复**，9 步幂等：
  环境体检 → 定位/克隆两端代码 → 建 venv 装依赖（失败自动换国内镜像）→ 打补丁
  → 写 `setting.toml` → 安装浏览器扩展 → 后台起服务 → **自动建项目/浏览器/空间/gpt_workflow 任务类型** → doctor 自检。
- `pool.bat test`（`scripts/selftest.py`）：**端到端自检**，真出一张图并校验图片魔数/体积。
- `pool.bat` 不带参数 → **中文数字菜单**（`scripts/menu.py`），双击即可用，不用记命令。
- `pool.bat reset`（`scripts/reset_pool.py`）：清场重置（停服务/关窗口/清缓存/清日志/可选解绑窗口池），**保留账号与 token**。
- `pool.bat install-skill`（`scripts/install_skill.py`）：把 Skill 装到 `~/.agents/skills/`（或 claude/codex/cursor），支持目录联接与卸载。
- `pool.bat patch`（`scripts/apply_patches.py`）：**不需要 git 的补丁应用器**，支持 `--check` / `--dry-run` / `--revert`。
- `pool.bat logs`（`scripts/tail_logs.py`）：跨平台看日志，`--errors` 只过滤错误行。
- `docs/00-新手必读.md`：术语扫盲 + 三条上手路径 + 分步“应该看到什么” + 12 个常见卡点 + 出师验收清单。
- `--json` 输出：`doctor` / `test` / `gen` / `batch`，便于程序与 Agent 调用（失败时带 `hint`）。
- `batch_gen.py --retry-failed`：只重跑上次报告里失败的条目。

### 开源工程化

- `README.md`（中文）+ `README.en.md`（English）：徽章、真实出图预览、实测数据、命令总表、文档索引、安全与合规
- `tests/`：**43 个离线单元测试**（补丁解析/应用/校验、错误自诊断、批处理检查、配置写入、日志轮转、凭据扫描）
- `.github/workflows/ci.yml`：三版本 Python 矩阵 ×（compileall / ruff / 凭据扫描 / 批处理检查 / 补丁自检 / pytest）+ CLI 冒烟作业
- `.github/ISSUE_TEMPLATE/*`、`PULL_REQUEST_TEMPLATE.md`：报障要求附上 `doctor` 输出与自查清单
- `SECURITY.md`：**明确列出安全边界**（长期 token、默认 admin/admin、API Key、插件桥、补丁改上游）与报告渠道
- `CODE_OF_CONDUCT.md`（Contributor Covenant v2.1 改编，新增「禁止发布他人凭据」）
- `pyproject.toml` / `requirements-dev.txt` / `.editorconfig`
- `.gitattributes`：**关键** —— `.bat` 强制 CRLF、`*.patch -text`（防止换行符被改导致补丁失效）
- `scripts/lint_bat.py`：批处理静态检查（ASCII / CRLF / 括号块 / 标签 / 引号）
- `scripts/scan_secrets.py`：凭据扫描（卡密、JWT、Token、厂商密钥、内网地址、明文密码），支持 `# scan-secrets:allow`
- `scripts/apply_patches.py --validate`：补丁自检（hunk 行数与 `@@` 头是否一致 + 是否夹带凭据）
- `docs/images/demo-output.jpg`：真实出图预览

### 安全修复

- **移除文档中的真实卡密**（`docs/04-build-pool.md` 曾包含真实邮箱/密码/2FA/`access_token`），改为 `demo_user01@example.com` 示例
- **移除补丁中的真实 API Key**：`patches/02-fpbrowser2api.patch` 里有一处上下文行紧邻上游自带的可用密钥。
  已去掉该 hunk 的后文上下文（代价：`git apply` 需加 `-C1`，内置应用器不受影响），并在 `patches/README.md` 说明原因
- 内网示例地址统一改为 `192.168.1.100`

### 改进（健壮性 / 易用性）

- **管理后台登录不再硬编码**：统一从 `setting.toml` 读 `admin_username/admin_password`，可用 `--fpb-password` / `FPB_ADMIN_PASSWORD` 覆盖。
- **安装依赖前先停服务**：避免在服务运行时替换 fastapi/uvicorn 导致服务崩溃。
- **启动失败直接展示日志尾部**，并自动识别 `ModuleNotFoundError` / 端口占用给出修法。
- **日志自动轮转**（超过 3 MB 只保留尾部 1 MB），长跑不会撑满磁盘。
- doctor 新增两项关键检查：**playwright 依赖**与**浏览器扩展是否已装/版本是否一致**；并修复之前被吞掉的路径告警。
- 错误信息带「下一步怎么做」：token 过期 / 插件未连接 / pageFetch 空 / 额度用尽 / 冷却中 / 服务未启动。
- 内部错误分类改用异常类（不再靠字符串匹配“提交/下载”判断退出码）。
- 图片校验支持 WEBP/BMP 魔数。
- 补丁重复应用不再报错（识别为「已打过补丁」并跳过）。

### 修复

- `pool.bat logs` 之前硬编码 `D:\fpbrowser2api` 路径，换目录就会失败。
- `pool.bat` 传参重构：用内联循环重拼参数（子程序里 `%1` 取不到脚本参数，会静默丢参）。
- 报告截图/临时文件不再被 `install_skill` 复制进全局 skills 目录。

## [1.0.0] - 2026-10-16

首个公开版本：把一次真实落地（VirtualBrowser + FPBrowser2API + 20 账号 ChatGPT 生图号池）
整理成可复用的脚本、文档与补丁。

### 新增

- `pool.bat` 统一入口：`start` / `stop` / `status` / `doctor` / `warm` / `sync` / `gen` / `batch` / `import` / `logs`
- `scripts/_common.py`：零硬编码的安装路径自动探测（`FPB_ROOT` / `VB_ROOT` / `VB_API_URL` / `FPB_API_URL` / `POOL_PYTHON` 可覆盖）
- `scripts/doctor.py`：9 类环境自检（Python / 路径 / 补丁 / 服务 / 公开 API / 内核 / 插件 / 号池 / 长连接），失败给修复指引
- `scripts/start_all.py` / `stop_all.py`：**后台无窗口**启停（`DETACHED_PROCESS`，日志落盘）
- `scripts/status_all.py`：服务 / 环境 / 长连接 / 窗口池 / token 到期 / 最近任务 看板
- `scripts/import_chatgpt_tokens.py`：卡密（含 `access_token`）直灌建池，幂等 + 自动备份
- `scripts/warmup_windows.py`：窗口池预热（插件首次连接 + 目标站首访 Cookie）
- `scripts/sync_vb_pool.py`：窗口同步 / 失效清理 / 任务池绑定
- `scripts/gen_image.py`：一行出图（自动选号 + token 授权下载 + 真图校验 + 抗反问重试）
- `scripts/batch_gen.py`：并发批量出图 + JSON 报告
- `patches/*.patch`：9 处上游必要改造
- `docs/`：QUICKSTART + 架构 / 安装 / 配置 / 建池 / 日常使用 / 运维 / 排错 / FAQ

### 修复（相对上游代码）

- api_server：内核路径探测支持自定义安装目录（`VB_BROWSER_EXE`）
- api_server：残留窗口进程检测 `wmic` → PowerShell CIM（Windows 11 24H2+ 必须）
- api_server：窗口启动失败自动清理残留进程与锁文件并重试
- api_server：补齐 `/api/isBrowserRunning`、`/api/randomizeFingerprint`、`/api/clearCache`
- api_server：MCP 依赖缺失时不再导致整个 REST API 起不来
- fpbrowser2api：窗口同步不再把同空间窗口误判为「跨空间」而永久跳过
- fpbrowser2api：VirtualBrowser 窗口的备注/账号/主页映射到窗口池
- fpbrowser2api：插件连接等待时间可配置（默认 10s → 30s）
- fpbrowser2api：结果图改用窗口 token 下载并校验真实图片格式

### 实测数据（20 账号 / 单机）

- 建池：20 账号导入 + 预热 ≈ 5 分钟
- 出图：单张 30–90s
- 6 并发：预热前 2/6，预热后 **6/6**（总耗时 83s）
