# 01 · 架构与数据流

## 一张图

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 调用方                                                                      │
│   · CLI:  pool.bat gen / batch                                             │
│   · HTTP: POST /v1/videos  (OpenAI 兼容, Authorization: Bearer <api_key>)   │
│   · 你的业务系统 / 中转站                                                    │
└───────────────────────────────┬────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ FPBrowser2API            127.0.0.1:8002                                     │
│                                                                             │
│  routes.py         /v1/videos  /v1/models  /v1/videos/{id}                  │
│  task_service.py   排队 → 选窗口（额度/并发/冷却）→ 执行 → 回写               │
│  task_handler_registry.py   task_type_code → 执行器                          │
│       └── gpt_workflow → gpt_task_executor.py                              │
│  browser_extension_bridge.py  WebSocket /api/extension/ws（space|window 维度）│
│  data/fpbrowser.db  SQLite：projects/browsers/spaces/windows/task_types/    │
│                     task_type_windows/tasks/platform_accounts               │
└───────┬───────────────────────────────────────────────────┬─────────────────┘
        │ HTTP（指纹浏览器控制）                              │ WebSocket（任务下发）
        ▼                                                   ▼
┌───────────────────────────────┐              ┌───────────────────────────────┐
│ VirtualBrowser 本地 API   :9000 │              │ 浏览器插件（每窗口一份）        │
│  /api/getBrowserList          │              │  background.js                │
│  /api/getBrowserFullParameters│              │   · hello → 注册 space|window │
│  /api/launchBrowser → CDP 端口 │              │   · task.start → 执行         │
│  /api/stopBrowser             │              │   · task.progress / task.done │
│  /api/isBrowserRunning★       │              │  在 chatgpt.com 页面上下文里   │
│  /api/randomizeFingerprint★   │              │  用 Bearer 长 token 调接口     │
│  /api/clearCache★             │              └───────────────────────────────┘
│  /api/addCrx /getCrxList      │                            ▲
└───────┬───────────────────────┘                            │ 注入扩展
        │ 启动内核 + --remote-debugging-port                  │
        ▼                                                     │
┌─────────────────────────────────────────────────────────────┴──────────────┐
│ VirtualBrowser 指纹窗口（一个账号一个 profile）                              │
│  %LOCALAPPDATA%\VirtualBrowser\Workers\<envId>                              │
│  · 独立 Cookie / localStorage / UA / Canvas / WebGL / 时区 / 代理            │
│  · chrome.storage.local 里持久化 fpb_*（插件配置）→ 重启自动重连              │
└────────────────────────────────────────────────────────────────────────────┘
   ★ = 本 Skill 的补丁新补/修补的接口（上游官方 16 项清单里没有）
```

## 关键设计：三种“身份”如何一一对应

| 身份 | 存在哪儿 | 用途 | 例子 |
|---|---|---|---|
| `envId`（VirtualBrowser 环境 ID） | `virtual.dat` | 指纹窗口，隔离 Cookie/代理/指纹 | `7` |
| `window_key` | FPBrowser2API `windows` 表 | **两边的桥**：等于 `envId` | `"7"` |
| `space_pk` + `window_key` | 插件注册键 | 插件用它找到「自己属于哪个任务池」 | `default\|7` |
| `mapping_id` | `task_type_windows` 行 | 「窗口 ⇄ 任务类型」绑定，额度/冷却/token 都挂在这里 | `12` |
| `sora_access_token` | `task_type_windows` 列 | 该窗口的长 token（**号池的核心资产**） | `eyJhbGci...` |

> **为什么能做到「不登录网页」**：`gpt_task_executor.gpt_workflow()` 取 token 的顺序是
> `call args → DB(task_type_windows.sora_access_token) → 浏览器会话`。
> 只要把卡密里的长 token 写进 DB，第 3 步就不会被触发，窗口不需要登录态。

## 一次任务的完整时序

```
调用方        FPBrowser2API          VirtualBrowser API        插件(窗口)         ChatGPT
  │  POST /v1/videos │                      │                     │                 │
  ├─────────────────►│ 建 task(queued)      │                     │                 │
  │                  │ 选窗口(window_pk=7)  │                     │                 │
  │                  │ ensure_open ────────►│ launchBrowser       │                 │
  │                  │                      ├─ 启动内核+CDP ──────►│                 │
  │                  │                      │◄─ debuggingPort ────┤                 │
  │                  │◄─ CDP 端口 ──────────┤                     │                 │
  │                  │ 打开中转页(带 fpb_*) ────────────────────► │ 读 hash → 存配置 │
  │                  │ 断开 CDP（降低自动化特征）                 │                 │
  │                  │                      │                     ├─ hello ────────►│(WS)
  │                  │◄──────────── hello.ok ─────────────────────┤                 │
  │                  │ task.start(token) ───────────────────────►│                 │
  │                  │                      │                     ├─ fetch Bearer ►│
  │                  │◄───────────── task.progress ───────────────┤                 │
  │                  │◄───────────── task.done(result_url) ───────┤                 │
  │                  │ 写回 tasks(status=completed, result_json)  │                 │
  │◄─ GET /v1/videos/{id} → completed + image_url ────────────────┤                 │
  │ 下载原图（带该窗口 token，否则 403）                             │                 │
```

## 数据库关键表

| 表 | 关键列 | 说明 |
|---|---|---|
| `projects` / `browsers` / `spaces` | `vendor`, `lan_addr`, `space_id` | 三级配置：项目 → 浏览器服务器（vendor=`virtualbrowser`）→ 空间（`default`） |
| `windows` | `space_pk`, `window_key`, `platform_account`, `platform_account_id`, `proxy_addr` | 同步自 VirtualBrowser |
| `task_types` | `code='gpt_workflow'`, `concurrency`, `total_concurrency` | 任务类型与并发策略 |
| `task_type_windows` | `task_type_id`, `window_pk`, `enabled`, `remaining_quota`, `sora_access_token`, `sora_access_expires`, `error_cooldown_until` | **窗口池绑定 + 长 token + 额度/冷却** |
| `tasks` | `task_id`, `status`, `progress`, `window_pk`, `result_json`, `error_message` | 任务与结果 |
| `platform_accounts` | `platform_username`(邮箱), `platform_password`, `platform_efa`(2FA) | 账号资料（换号重登用） |
| `system_config` | `api_key`, `debug_enabled`, `browser_open_concurrency` | 全局配置（**此处的 api_key 覆盖 setting.toml**） |

## 本 Skill 的补丁为什么必要

| # | 位置 | 不修会怎样 |
|---|---|---|
| 1 | api_server 内核路径探测 | 非默认安装目录直接报「未找到内核」 |
| 2 | api_server `_list_worker_pids`（wmic→CIM） | Windows 11 24H2+ 已删 wmic → 残留进程检测永远为空 → 窗口启动即退出（`exit_code=0`） |
| 3 | api_server 启动失败自动清理+重试 | 上面的坑要人工介入 |
| 4 | api_server 补 3 个接口 | FPBrowser2API 调 `/api/isBrowserRunning`、`/api/randomizeFingerprint`、`/api/clearCache` 会 404 |
| 5 | api_server 可选 MCP 依赖 | `mcp` 2.x 改名 FastMCP，import 失败 → 整个服务起不来 |
| 6 | fpb `database.upsert_windows` | 同空间窗口被判「跨空间」永久跳过 → 窗口改名/换代理同步不回来 |
| 7 | fpb `_vb_list_windows` 字段映射 | 后台看不到「哪个窗口绑哪个账号」 |
| 8 | fpb 插件连接等待可配置 | 新池冷启动 → 前几轮任务报「插件未连接」 |
| 9 | fpb 结果图下载（token + 校验） | 保存 33 字节错误 JSON 却提示 SUCCESS |

细节与手动改法见 [../patches/README.md](../patches/README.md)。
