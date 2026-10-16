# 03 · 配置

分四处：**(A) 调度网关 setting.toml**、**(B) VirtualBrowser 本地 API**、
**(C) 管理后台/数据库**、**(D) 环境变量**。

---

## A. 调度网关 `config/setting.toml`

```toml
[server]
host = "0.0.0.0"
port = 8002                # 本 Skill 默认；与 pool.bat / 插件 base_url 保持一致

[global]
api_key = "改成你自己的密钥"  # 对外调用用；**首次启动会写进数据库，之后以数据库为准**

[system]
proxy_enabled = false
debug_enabled = false      # 排错时置 true，日志会详细很多
log_to_file = true         # 写 app.log

[extension_executor]       # ★ 本方案的核心：任务走浏览器插件长连接
enabled = true
base_url = "127.0.0.1:8002"        # 插件连接 ws://<base_url>/api/extension/ws
bridge_token = "fpb-bridge-secret"  # 插件鉴权；留空=不校验
connect_wait_seconds = 30          # 新池冷启动等待（补丁新增，默认 30）
task_timeout_seconds = 1800        # 单任务总超时
```

要点：

| 项 | 说明 |
|---|---|
| `enabled = true` | 不开的话任务会走 Playwright/CDP 旧模式，本号池方案依赖插件模式 |
| `base_url` | 指纹浏览器和网关**不在同一台机器**时，填网关的局域网 IP，例如 `192.168.1.100:8002` |
| `bridge_token` | 非空时插件必须带 token（中转页会自动附上）。为 0 安全时可留空 |
| `connect_wait_seconds` | 窗口越多/机器越慢，越要大 |

**改完必须重启网关**：`pool.bat stop && pool.bat start`

---

## B. VirtualBrowser 本地 API

无配置文件，用环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `VB_API_PORT` | 9000 | 本地 API 端口 |
| `VB_BROWSER_EXE` | 自动探测 | 内核 `VirtualBrowser.exe` 绝对路径 |
| `VB_TAKEOVER_EXTERNAL_WINDOW` | 1 | 检测到「客户端手工启动的窗口」时自动结束并以带 CDP 端口的方式重启。设 `0` 关闭 |

```bat
setx VB_API_PORT 9000
setx VB_BROWSER_EXE "D:\VirtualBrowser\VirtualBrowser\151.0.7922.47\VirtualBrowser.exe"
```

> **重要习惯**：不要在 VirtualBrowser 客户端 UI 上点「启动」跑任务用的窗口。
> 那种窗口没有 CDP 调试端口，自动化接不进去（补丁会尝试接管，但会多花时间）。
> 观测环境状态就只用客户端看，启动交给号池。

---

## C. 管理后台与数据库

后台：<http://127.0.0.1:8002/> → 默认 **admin / admin**（首次登录后请改密码）。

必须核对的位置（后台 → 系统配置 / 浏览器服务器 / 空间 / 任务类型）：

| 位置 | 应填 |
|---|---|
| 公开 API Key | 你对外调用用的 key（`system_config.api_key`，**优先于 setting.toml**） |
| 浏览器服务器 → vendor | `virtualbrowser`（或 `vb`） |
| 浏览器服务器 → lan_addr | `http://127.0.0.1:9000` |
| 浏览器服务器 → access_key | 留空（开源 api_server 不校验） |
| 空间 → 空间ID | `default`（同步全部窗口）或指定分组 |
| 任务类型 → 处理器 | `gpt_workflow`（GPT/ChatGPT 图片/视频生成） |

建议的并发设置（`task_types` 表）：

| 列 | 含义 | 建议 |
|---|---|---|
| `concurrency` | 单窗口并发 | `1`（一个窗口同时只跑一个任务最稳） |
| `total_concurrency` | 池总并发 | ≤ 窗口数（20 窗口可设 20） |
| `window_call_cooldown_seconds` | 同窗口两次任务间隔 | 20–30 |
| `error_retry_count` | 失败重试次数 | 0–1（免费号不要太多重试） |

改法：后台「任务类型管理」页面，或 `pool.bat doctor` 报错时按提示设置。

---

## D. 环境变量（可选，覆盖自动探测）

| 变量 | 作用 |
|---|---|
| `FPB_ROOT` | FPBrowser2API 代码目录 |
| `VB_ROOT` | VirtualBrowser 安装目录 |
| `VB_API_URL` | 例 `http://127.0.0.1:9000` |
| `FPB_API_URL` | 例 `http://127.0.0.1:8002` |
| `FPB_API_KEY` | 公开 API Key（免去每个命令传 `--api-key`） |
| `POOL_PYTHON` | 指定 Python 解释器 |
| `FPB_EXTENSION_BRIDGE_URL` | 强制插件 WS 地址（跨机部署时用） |

用 `pool.bat doctor` 的「路径解析」一节可以确认当前生效值。

---

## 配置自检清单（复制粘贴用）

```bat
pool.bat doctor
```

逐项确认：

- [ ] 第 2 节路径解析 4 项全 OK
- [ ] 第 3 节 9 处补丁全 OK
- [ ] 第 4 节两个服务端口已监听
- [ ] 第 5 节 `/v1/models` 可用（说明 API Key 正确）
- [ ] 第 6 节内核存在 + 插件已注册
- [ ] 第 7 节窗口池有绑定、token 有效期正常
