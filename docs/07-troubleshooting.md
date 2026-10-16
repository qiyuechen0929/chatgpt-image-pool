# 07 · 排错手册

> 用法：先 `pool.bat doctor`，再按症状查表。每条都写清 **根因** 与 **验证方式**。

---

## 0. 三条通用诊断命令

```bat
pool.bat doctor          :: 9 类检查，逐项给修复指引（--json 供程序解析）
pool.bat test            :: 端到端自检：真出一张图（比 doctor 更接近真实链路）
pool.bat logs --errors   :: 只看错误相关行
pool.bat status          :: 服务/窗口/额度/token 到期/冷却
```

**排错顺序（照这个顺序做，90% 问题能自己解决）**：

```bat
pool.bat doctor          :: 1. 环境/依赖/补丁/服务哪一项不对
pool.bat test            :: 2. 链路能不能出图（会给出“→ 建议”）
pool.bat logs --errors   :: 3. 看具体报错
pool.bat reset && pool.bat start && pool.bat warm   :: 4. 状态混乱时的终极三连（保留账号）
pool.bat setup           :: 5. 还不行 → 让它自动修依赖/补丁/配置/扩展
```

日志位置：

| 服务 | 日志 |
|---|---|
| VirtualBrowser 本地 API | `<FPB_ROOT>\logs\vb_api.out.log` / `.err.log` |
| FPBrowser2API | `<FPB_ROOT>\logs\fpb.out.log` / `.err.log`（另有 `app.log`） |

---

## 1. 建池 / 环境

| 症状 | 根因 | 处理 | 验证 |
|---|---|---|---|
| `未找到 VirtualBrowser Chromium 内核执行程序` | 内核路径没探测到（自定义安装目录） | `setx VB_BROWSER_EXE "<...>\<版本>\VirtualBrowser.exe"` | `doctor` 第 6 节显示内核路径 |
| 窗口启动后**立刻退出**，`exit_code=0`，日志出现「请在现有的浏览器会话中打开」 | 该 profile 被**残留进程**占锁。旧代码用 `wmic` 检测，而 Windows 11 24H2(26200+)**已删除 wmic** → 检测恒为空 | 补丁已改为 PowerShell CIM 查询 + 启动失败自动清理重试。仍失败：`pool.bat stop` 后再启动 | `doctor` 第 3 节 `_list_worker_pids` 命中 |
| 同步窗口总是 `skipped`，提示「跨项目空间窗口」 | 上游 `upsert_windows` 把**同空间**已有窗口也当成「已转移到其它空间」而跳过 | 补丁 #6 修复 + `pool.bat sync` 主动清理失效窗口 | `sync` 输出 `affected=N skipped=0` |
| 后台看不到「哪个窗口绑哪个账号」 | 上游没把 VirtualBrowser 的 `remark` 映射到窗口池 | 补丁 #7 | `status` / 后台窗口列表能看到邮箱 |
| 窗口启动失败 `CDP 端口超时` | 内核被杀软/权限拦住 | 手动双击内核 exe 看是否弹窗；加白名单 | `curl :9000/api/getBrowserRunningList` 有该窗口 |
| `pool.bat doctor` 报「未找到空间 / gpt_workflow 任务类型」 | 全新安装还没有号池骨架 | `pool.bat setup`（自动建项目/浏览器/空间/任务类型） | `doctor` 第 7 节能识别到 `space_pk` 与 `task_type_id` |
| 安装依赖后服务莫名挂了 | pip 在服务运行时替换了 fastapi/uvicorn | 已修：`setup` 会先停服务再装；手动装包前先 `pool.bat stop` | `pool.bat start` 后端口重新监听 |

---

## 2. 插件长连接

| 症状 | 根因 | 处理 |
|---|---|---|
| `浏览器插件未连接：space_id='default' window_key='N'` | 新窗口冷启动 + 扩展初始化超过等待时间 | ① `pool.bat warm --keys N` ② `setting.toml [extension_executor] connect_wait_seconds = 60` ③ 确认插件已注册（`doctor` 第 9 节） |
| `doctor` 报「未安装浏览器扩展」 | `<VB_ROOT>\extensions\fp_browser_extension` 不存在 | `pool.bat setup`（会从 `<FPB_ROOT>\browser_extension` 自动复制） |
| `doctor` 报「缺 playwright」 | 依赖没装全（预热/开窗需要它） | `pool.bat setup`，或 `<venv>\python.exe -m pip install playwright` |
| `GPT pageFetch returned empty result for /backend-api/f/conversation` | 该 profile 从未访问过 chatgpt.com（无 Cookie/cf_clearance） | `pool.bat warm`（预热会访问一次目标站）；单独补：`pool.bat warm --keys N` |
| `/api/extension/clients` 永远为空 | 插件没注入 or 没打开过中转页 | ① `curl :9000/api/getCrxList` 有 `FPBrowser2API Bridge` ② 插件注册后**新启动**的窗口才有 ③ 任务/预热会打开中转页触发连接 |
| 桥接握手被拒 `code 1008` | 插件 token 与 `setting.toml` 的 `bridge_token` 不一致 | 两边改一致，或都把 token 留空 |
| 跨机部署时插件连不上 | `base_url` 指向了 `127.0.0.1` | 改成网关**局域网 IP**（如 `192.168.1.100:8002`），并放行防火墙 |

---

## 3. 任务执行

| 症状 | 根因 | 处理 |
|---|---|---|
| `GPT access token not found: {"WARNING_BANNER"...}` | 窗口池里没有 token，或 token 已过期（返回的是未登录页面） | `pool.bat import accounts.txt --yes`；`doctor` 第 7 节看到期时间 |
| `缺少 GPT access_token，无法读取余额` | 同上（余额刷新走 token） | 同上 |
| HTTP 400 `gpt-image2-1k must set duration=4` | 给图片模型传了 `duration`/`seconds` 且不等于 4 | 不传，或传 4 |
| 任务卡在 `processing` 很久 | 窗口被风控/页面卡死/网络慢 | 看 `status` 的冷却；`POST :9000/api/stopBrowser {"id":N}` 后重试；换号 |
| 模型回一段文字（`已生成：…` / `你更喜欢…`）但没出图 | 免费号偶发「只回文字/反问」，尤其裸提示词 | `gen_image.py` 已内置**加固重试**（`--retries`，默认 2）；仍失败就换措辞或换号 |
| 任务成功但 `image_url` 下载 403 | 结果图是内部鉴权链接 | 用 `gen_image.py`（自带 token 下载）；或开 `[r2]`/`[oss]`；见 [05-daily-use.md](05-daily-use.md#c4-取回图片关键) |
| 保存的图只有几十字节 / 0 KB | 把错误 JSON 当图片存了 | 用 `gen_image.py`（会校验 PNG/JPEG 魔数）；自查文件头 `89 50 4E 47` |
| 连续失败后窗口不再被选中 | 任务池进入了错误冷却 | `status` 看「冷却」列；等解冻，或后台清冷却 |

---

## 4. 服务与端口

| 症状 | 根因 | 处理 |
|---|---|---|
| 任务突然全部失败、`Connection refused` | 服务被关掉了（旧版跑在可见控制台窗口里，容易误关） | 用 `pool.bat start`（后台无窗口）；`doctor` 第 4 节确认 |
| `netstat` 看不到端口但 `curl` 通 | Windows 上监听行可能显示为 PID 0（权限） | 以 `curl`/`doctor` 为准 |
| 端口被占用 | 已有实例或别的程序 | `pool.bat stop` 后重启；或改端口（`setting.toml` + `VB_API_PORT`） |
| 改了 `setting.toml` 不生效 | 服务没重启 / 数据库里的值优先 | `pool.bat stop && pool.bat start`；API Key 以数据库为准 |
| MCP 导入报错导致服务起不来 | `mcp` 2.x 把 `FastMCP` 改名为 `MCPServer` | 补丁 #5 已容错；或 `pip install "mcp<2"` |

---

## 5. 数据库 / 号池

| 症状 | 根因 | 处理 |
|---|---|---|
| 窗口池为空 | 没导入卡密 / 空间不对 | `pool.bat import accounts.txt --yes`；确认 `doctor` 显示的空间 |
| 重复执行导入会不会重复建环境 | 不会，脚本按邮箱 upsert | 放心重跑 |
| 想回滚一次导入 | 导入前会自动备份 | `data/fpbrowser.bak-<时间戳>.db` 覆盖回去，然后 `pool.bat start` |
| `database is locked` | 并发写（后台页面 + 脚本同时写） | 关掉后台页面重跑；脚本本身有 20–30s 超时与事务 |
| 手滑删了 `data/fpbrowser.db` | — | 从备份恢复；没有备份则重新导入卡密 + `pool.bat sync`（环境与登录态还在） |

---

## 6. 网络与风控

| 症状 | 根因 | 处理 |
|---|---|---|
| 所有号同时开始失败 | 出口 IP 被标记 / 站点策略变化 | 换代理、降并发、隔一段时间再跑 |
| 某些号总是失败，其它正常 | 该号被限制或额度耗尽 | `status` 看额度；`pool.bat import` 换新号 |
| 出口 IP 与预期不符 | 窗口没走代理或代理失效 | 窗口内访问 <https://browserleaks.com/ip> 核对；用 `updateBrowser` 重设代理 |

---

## 7. 收集排错信息（提 issue/求助时用）

```bat
pool.bat doctor > doctor.txt 2>&1
pool.bat status > status.txt 2>&1
pool.bat logs   > logs.txt   2>&1
sqlite3 D:\fpbrowser2api\data\fpbrowser.db "select task_id,status,progress,window_pk,substr(error_message,1,200) from tasks order by id desc limit 20" > tasks.txt
```

**贴出来之前必须先删掉：** API Key、token 字符串、账号密码、代理账号密码。
`doctor`/`status` 默认只显示邮箱与「token 有无+到期」，可以放心贴。
