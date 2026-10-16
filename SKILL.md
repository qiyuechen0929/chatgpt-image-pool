---
name: chatgpt-image-pool
description: "搭建与运维 ChatGPT 生图号池（VirtualBrowser 指纹浏览器 + FPBrowser2API 调度网关）。Use when the user wants to build a ChatGPT image-generation account pool, import ChatGPT 卡密/accounts with access_token into a browser pool, run concurrent text-to-image jobs across many accounts, warm up fingerprint browser windows, debug 插件未连接 / pageFetch empty / 401 token / 403 estuary download issues, or generate images in bulk via /v1/videos. Keywords: 生图号池, 号池搭建, chatgpt生图, gpt-image-2, 卡密导入, 指纹浏览器出图, VirtualBrowser, FPBrowser2API, 批量出图, 并发出图, 插件长连接, warmup, account pool, image pool, text-to-image automation."
---

# ChatGPT 生图号池（搭建 + 运维）

一个把 **VirtualBrowser 指纹浏览器** 与 **FPBrowser2API 调度网关** 打通的操作手册，
让 N 个 ChatGPT 账号变成一个可并发调用的出图池。

## 何时使用本 Skill

| 用户说 | 你要做的 |
|---|---|
| 「帮我搭一个 ChatGPT 生图号池 / 出图池」 | **一条命令：`pool.bat setup`**（幂等，自动建环境/打补丁/建空间/起服务），然后照下面「交付话术」回给用户 |
| 「我小白，怎么开始」 | 让用户读 [docs/00-新手必读.md](docs/00-新手必读.md)，或直接替他把 `pool.bat setup` 跑到全绿 |
| 「这堆卡密（邮箱----密码----2FA----token）导入号池」 | 卡密导入（B 段） |
| 「批量出图 / 并发出图 N 张」 | 出图（C 段） |
| 「任务报错了：插件未连接 / pageFetch empty / 401 / 403」 | 排错（D 段）；先跑 `pool.bat test` 复现 |
| 「号池现在什么状态 / token 还有多久过期」 | `pool.bat status`（人看） / `pool.bat doctor --json`（程序看） |
| 「环境坏了 / 重装 / 乱掉了」 | `pool.bat setup`（修复）→ 不行再 `pool.bat reset` → `pool.bat warm` |

## 首选路径：能不动手就不动手

搭建/修复环境**不需要看下面的 A 段细节**，直接：

```bat
pool.bat setup        # 9 步全自动、幂等：体检→定位/克隆→venv依赖→打补丁→写配置→装扩展→起服务→建空间→自检
```

- 失败时它会**逐条给出「→ 怎么修」**，修完**再跑一次同样命令**即可（不会重复建）。
- `--skip-start` 只装环境；`--no-clone` 不自动克隆；`--vb-root/--fpb-root` 指定目录。
- 装完用 `pool.bat test` 做端到端验收（真出一张图 + 校验图片魔数）。

## 能力清单（本 Skill 提供的命令）

```bat
pool.bat                  # 不带参数 = 中文数字菜单（小白推荐，双击即可）
pool.bat setup            # ★ 一键搭建/修复（幂等）
pool.bat test             # ★ 端到端自检：真出一张图，验证整条链路
pool.bat doctor           # 环境自检（新增：playwright 依赖 + 浏览器扩展是否已装）
pool.bat start | stop | status
pool.bat import accounts.txt --yes    # 卡密 → 建环境 → 绑定任务池 → 写长 token
pool.bat warm                         # 窗口池预热（新池必跑一次）
pool.bat sync                         # 窗口同步/清理/绑定任务池
pool.bat gen "提示词" -o out.png       # 一张出图（自动选号 + 带 token 下载 + 真图校验）
pool.bat batch prompts.txt --concurrency 4 [--retry-failed]
pool.bat reset            # 清场重置（停服务/关窗口/清缓存/清日志，保留账号与 token）
pool.bat patch            # 打/还原上游补丁（内置应用器，**不需要 git**）
pool.bat logs --errors    # 看日志（含 ERROR/Traceback 过滤）
pool.bat install-skill    # 把本 Skill 装到 ~/.agents/skills/ 供任意会话调用
```

### 机器可读输出（Agent 优先用这个）

`doctor` / `test` / `gen` / `batch` 都支持 `--json`：

```bat
pool.bat doctor --json     # {"ok": true, "failed": [], "warned": [], "log": [...]}
pool.bat test   --json     # {"ok": true, "saved_path": "...", "bytes": 1390780, "task_id": "...", "attempts": 1}
pool.bat gen "..." --json  # {"ok": true, "saved_path": "...", "bytes": ..., "image_url": "..."}
                           # 失败时：{"ok": false, "error": "...", "hint": "下一步怎么做"}
```

**Agent 执行约定**：先 `doctor --json` 判断环境 → 再做动作 → 用 `test --json` 验收；
失败时先读 `error`+`hint`，不要盲目重试；涉及写库的动作（import/reset --purge-pool）必须先向用户确认。

### 环境变量（零硬编码路径的覆盖开关）

| 环境变量 | 作用 |
|---|---|
| `FPB_ROOT` | FPBrowser2API 代码目录（默认自动探测 `D:\fpbrowser2api` 等） |
| `VB_ROOT` | VirtualBrowser 安装目录（含 `VirtualBrowser.exe`） |
| `VB_API_URL` | VirtualBrowser 本地 API 地址（默认 `http://127.0.0.1:9000`） |
| `FPB_API_URL` | FPBrowser2API 地址（默认读 `setting.toml` 的端口，通常 `:8002`） |
| `POOL_PYTHON` | 指定用哪个 Python 跑脚本（默认项目 `.venv`） |

---

## A. 从零搭建（用户第一次用）

### A1. 前置检查

先跑自检，它会告诉你缺什么：

```bat
pool.bat doctor
```

典型输出里的 FAIL 及处理：

| FAIL 项 | 处理 |
|---|---|
| 未找到 FPBrowser2API 代码目录 | clone `https://github.com/yang0/fpbrowser2api`，或设 `FPB_ROOT` |
| 未找到 VirtualBrowser api_server | clone `https://github.com/yang0/VirtualBrowser` 取其 `api_server/` |
| 有 N 处补丁未打 | 见 A2 |
| 服务未监听 | `pool.bat start` |
| 没有注册任何插件 | 注册扩展：`POST :9000/api/addCrx`（见 docs/03-configure.md） |
| 任务池是空的 | `pool.bat import accounts.txt --yes` |

### A2. 打补丁（必须，但**不需要 git**）

上游代码有 9 处必须改造（内核路径探测、wmic 在新系统被移除、同步逻辑 bug、
结果图 token 下载等）。**逐条原因见 `patches/README.md`**。

推荐直接用内置应用器（不依赖 git；已用「上游原始文件 → 打补丁 → 与线上运行文件逐字节比对」验证）：

```bat
pool.bat patch              :: 应用全部补丁（已打过会自动跳过）
pool.bat patch --check      :: 只检查是否已打全
pool.bat patch --revert     :: 还原上游代码（排查“是不是补丁导致的”时用）
```

用 git 也可以（二选一。`-C1` 是必需的：有一处 hunk 故意只带前文上下文，见 `patches/README.md` 的「关于密钥」）：

```bash
# 在 VirtualBrowser 仓库根目录（api_server 的上一级）
git apply -p1 -C1 --ignore-whitespace <skill>/patches/01-virtualbrowser-api_server.patch
# 在 fpbrowser2api 仓库根目录
git apply -p1 -C1 --ignore-whitespace <skill>/patches/02-fpbrowser2api.patch
```

打完后 `pool.bat doctor` 的第 3 节应全绿。（`pool.bat setup` 已包含本步骤。）

### A3. 启动并验证

```bat
pool.bat start
pool.bat doctor
pool.bat test          :: 真出一张图（最终验收）
```

两个服务会用 `DETACHED_PROCESS` 后台运行（**没有控制台窗口**，不会被误关），
日志在 `<FPB_ROOT>\logs\`（启动时自动轮转，不会无限长大）。查看：`pool.bat logs`。

---

## B. 卡密导入（建池）

### B1. 判断卡密类型

| 卡密格式 | 走哪条路 |
|---|---|
| `邮箱----密码----2FA----access_token`（**四段，带 token**） | ✅ 本 Skill 的**长 token 直灌**：`pool.bat import`（无需登录网页，绕过 Cloudflare/验证码） |
| `邮箱----密码----2FA`（三段，无 token） | 用上游的 `scripts/batch_bind_chatgpt.py` 走浏览器自动登录 |

### B2. 导入

```bat
:: 先导 1 个验证链路（强烈建议）
pool.bat import accounts.txt --only 1 --yes
pool.bat gen "测试：一只柴犬宇航员" -o out/_smoke.png

:: 确认能出图后全量导入（幂等，可重复执行）
pool.bat import accounts.txt --yes

:: 换新卡密（环境已存在，只更新账号与 token）
pool.bat import accounts.txt --no-create-envs --yes

:: 每个窗口一个独立代理（proxies.txt 按行对应卡密顺序）
pool.bat import accounts.txt --proxy-file proxies.txt --yes
```

脚本会：校验 token（直连 `/backend-api/me`）→ 建/复用环境（名 `ChatGPT-Worker-NN`，备注=邮箱）
→ 同步窗口并清理失效窗口 → 写 `platform_accounts` + 窗口绑定 + 任务池 token。写库前自动备份 DB。

### B3. 预热（新池必做，一次即可）

```bat
pool.bat warm                # 全部窗口
pool.bat warm --keys 6,16    # 只补失败的窗口
```

不预热的后果：前几轮任务报 `浏览器插件未连接` 或 `GPT pageFetch returned empty result`。
原理见 `docs/04-build-pool.md#为什么要预热`。

---

## C. 出图

### C1. 单张

```bat
pool.bat gen "一只戴耳机的柴犬，扁平插画风" --ratio 1:1 -o out/shiba.png
pool.bat gen "产品图：银色机械键盘，白色背景" --res 2k --style product -o out/kb.png
:: 提示词含标点/特殊符号时改用文件传入（cmd 会吃掉某些字符）
pool.bat gen --prompt-file prompt.txt --ratio 16:9 -o out/poster.png
```

`--res 1k|2k|4k`、`--ratio 1:1|16:9|9:16|4:3|3:4`、`--style realistic|cyberpunk|anime|concept_art|oil_painting|product`、
`--prompt-file <file>`（建议：提示词含标点时用它）、`--raw-prompt`（不扩写）、`--retries N`（抗反问重试）、`--json`（机器可读输出）。

### C2. 批量并发

```bat
pool.bat batch prompts.txt --outdir out --concurrency 4
pool.bat batch --outdir out --retry-failed     :: 只重跑上次报告里失败的条目
```

- `prompts.txt`：每行一条提示词（`#` 注释）
- 产出：`out/001_<时间戳>.png` … + `out/_batch_report.json`
- 并发数建议 ≤ 窗口数；每个窗口同时只跑一个任务更稳
- 失败项会带上「→ 下一步怎么做」（token 过期 / 插件未连接 / 冷却中 …）

### C3. 用 HTTP API 对接自己的系统

```bash
# 1) 取 API Key（管理后台可见，或读数据库）
#    sqlite3 data/fpbrowser.db "select api_key from system_config where id=1"
# 2) 提交
curl -X POST http://127.0.0.1:8002/v1/videos \
  -H "Authorization: Bearer <API_KEY>" -H "Content-Type: application/json" \
  -d '{"model":"gpt-image2-1k","prompt":"...","aspect_ratio":"1:1"}'
#    ⚠️ 图片模型经 /v1/videos 提交时不要传 duration/seconds（服务端自动置 4；若传必须=4）
# 3) 轮询 GET /v1/videos/{id} → status=completed → image_url
#    ⚠️ image_url 是内部 estuary 链接，下载必须带该窗口的 token（否则 403）
```

---

## D. 排错（高频问题）

| 症状 | 根因 | 处理 |
|---|---|---|
| `浏览器插件未连接：space_id='default' window_key='N'` | 新窗口冷启动 + 扩展初始化超过等待时间 | `pool.bat warm --keys N`；或在 `setting.toml [extension_executor]` 调大 `connect_wait_seconds` |
| `GPT pageFetch returned empty result for /backend-api/f/conversation` | 该 profile 从未访问过 chatgpt.com（无 cookie/cf_clearance） | `pool.bat warm`（会顺便访问一次目标站） |
| `GPT access token not found` | 窗口池里没有 token 或 token 过期 | `pool.bat import accounts.txt --yes`；用 `pool.bat doctor` 看有效期 |
| 任务成功但下载的图 0 KB / 33 字节 | 下载时没带 token（拿到的是 `{"detail":...}`） | 用 `gen_image.py`（内置 token 下载 + 图片格式校验） |
| 窗口启动立刻退出 `exit_code=0` | profile 被残留进程占用（新系统已无 wmic，旧检测失效） | 补丁已自动清理 + 重试；仍失败先 `pool.bat stop` 再启动 |
| HTTP 400 `must set duration=4` | 给图片模型传了 `duration` | 不传 `duration`，或传 4 |
| 模型回一段文字（"已生成/你更喜欢…"）没出图 | 免费号偶发只回文字 | `gen_image.py` 会自动用加固提示词重试；仍多次失败就换号/换措辞 |
| `pool.bat doctor` 报内核未找到 | 自定义安装目录 | 设 `VB_BROWSER_EXE=<...>\VirtualBrowser.exe` |
| doctor 报「缺 playwright」 | 依赖没装全 | `pool.bat setup`（会自动补装） |
| doctor 报「未安装浏览器扩展」 | `extensions\fp_browser_extension` 不存在 | `pool.bat setup`（自动从 `<FPB_ROOT>\browser_extension` 复制） |
| 状态越跑越乱 / 窗口卡死 | 残留进程与缓存 | `pool.bat reset`（保留账号）→ `pool.bat start` → `pool.bat warm` |
| 服务莫名停了 | 依赖安装在服务运行时被替换 | 已修：setup 会先停服务再装依赖；手动装包时先 `pool.bat stop` |

完整排错表（含日志位置、诊断命令）见 `docs/07-troubleshooting.md`。

> 一劳永逸的排错顺序：`pool.bat doctor` → `pool.bat test` → `pool.bat logs --errors`
> → `pool.bat reset && pool.bat start && pool.bat warm`。

---

## E. 运维要点（长期跑）

1. **服务后台化**：`pool.bat start` 无窗口；**不要**用前台窗口跑（误关=停服）。
2. **token 生命周期**：`pool.bat doctor` / `status_all.py` 显示到期时间；≤2 天预警；过期重新导入。
3. **窗口数 vs 内存**：每窗口 300–500 MB；任务结束后窗口会保留，长时间不用可 `pool.bat stop`。
4. **代理隔离**：同一 IP 跑太多号有联动风险，用 `--proxy-file` 每窗口一个独立出口。
5. **额度观察**：`status_all.py` 显示每个窗口 `remaining_quota` 与错误冷却。
6. **出问题先自愈**：`pool.bat reset` → `pool.bat start` → `pool.bat warm` 能解决绝大多数「越跑越乱」。

---

## F. 边界与红线（务必转达用户）

- 仅用于**自有账号**的技术研究与自动化；遵守目标站点条款与当地法律。
- 卡密/token/密码是敏感凭据：不要写进代码仓库，不要外发（`.gitignore` 已覆盖 `accounts.txt`、`*.db`、`logs/`）。
- 不要用本 Skill 做批量滥用、绕过付费、攻击或任何违法用途。

## G. 交付约定（Agent 执行规范）

1. **先诊断再动手**：任何操作前先跑 `pool.bat doctor`，把 FAIL 当作待办清单。
2. **改动上游代码只通过补丁**：不要手改散落文件；补丁在 `patches/`，改完复核 `doctor` 第 3 节。
3. **写库前必须备份**：`import_chatgpt_tokens.py` 已内置备份；自己写脚本也要备份 `data/fpbrowser.db`。
4. **不要泄露凭据到日志/输出**：打印账号时只显示邮箱，token 一律只显示「有/无 + 到期时间」。
5. **验收标准**：`doctor` 全绿 + 至少 1 张真实出图（PNG 且 >100 KB）才算完成；
   优先用 `pool.bat test --json` 拿到客观证据（`ok/bytes/saved_path`）。
