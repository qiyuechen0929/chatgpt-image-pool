# 06 · 运维

## 启停

```bat
pool.bat               :: 不带参数 = 中文数字菜单（双击即用）
pool.bat setup         :: 一键搭建/修复环境（幂等，最省事）
pool.bat test          :: 端到端自检（真出一张图）
pool.bat start         :: 后台无窗口启动两个服务（已在跑则跳过）
pool.bat stop          :: 关所有指纹窗口 + 停服务（--keep-windows 只停服务）
pool.bat status        :: 状态看板
pool.bat logs --errors :: 只看错误日志行
```

### 状态混乱时的一键恢复

```bat
pool.bat reset                    :: 停服务 + 关窗口 + 清缓存 + 清日志（保留账号/token）
pool.bat reset --purge-pool --yes :: 额外解绑窗口池与结束进行中任务
pool.bat reset --windows-only     :: 只关窗口清缓存
pool.bat reset --services-only    :: 只停服务
pool.bat reset --dry-run          :: 先看它要做什么
pool.bat start ^&^& pool.bat warm  :: 重建干净状态
```

> `reset` **不会**删账号、卡密、token——那是你的资产；只有 `--purge-pool` 会解绑窗口池（重新导入卡密即可恢复）。

服务以 `DETACHED_PROCESS` 运行，**没有控制台窗口**：

- 不会因为误关窗口而停服（这是早期最常见的「莫名其妙失败」原因）
- 日志在 `<FPB_ROOT>\logs\`：`vb_api.out.log` / `vb_api.err.log` / `fpb.out.log` / `fpb.err.log`

### 让它开机自启（可选）

任务计划程序 → 创建任务：
- 触发器：登录时
- 操作：程序 `D:\生图号池搭建skill\pool.bat`，参数 `start`
- 勾选「不管用户是否登录都要运行」需填密码；或仅在登录时运行即可

---

## 日常巡检

```bat
pool.bat status
```

看四件事：

| 看什么 | 正常 | 处理 |
|---|---|---|
| 服务 | 两行 `[OK]` | `pool.bat start` |
| 在线窗口 | 任务期间有若干 | 空闲时 0 也正常 |
| **token 到期** | > 2 天 | 临近/过期 → 重新导入卡密 |
| 冷却 / 额度 | 冷却为空、额度 > 0 | 冷却等它自己解冻；额度归零换号 |

```bat
pool.bat doctor
```

`doctor` 比 `status` 更严格（连补丁、内核、插件都要查），建议**每天第一次跑**。

---

## 扩容（加号）

1. 新卡密写进 `accounts_new.txt`
2. 环境编号要接着现有序号（避免重名）：

```bat
pool.bat import accounts_new.txt --start-index 21 --yes
pool.bat warm --keys 21,22,23        :: 只预热新窗口
```

3. 确认任务池并发上限：后台改 `task_types.total_concurrency ≥ 窗口数`

**内存预算**：每窗口 300–500 MB（空闲约 250 MB，出图时更高）。
20 窗口建议 ≥ 16 GB，40 窗口建议 ≥ 32 GB。

## 缩容 / 换号

```bat
:: 停用某个窗口（保留环境与账号记录）
:: 后台「任务类型管理」→ 窗口池 → 取消勾选「启用」
:: 或临时停一批：
pool.bat stop        :: 全部停掉（窗口会关，登录态/token 都保留）
```

不要直接删 `data/fpbrowser.db`，也不要手删 `Workers\<id>` —— 那等于把登录态与指纹整没了。

---

## 代理分配

### 为什么需要

同一出口 IP 上跑多个 ChatGPT 账号，容易被判定为关联。**每窗口一个独立出口**是最低成本的风控缓解。

### 方式 1：本地多端口代理（Clash/Mihomo 多端口转发）

```yaml
# 用代理客户端把不同节点映射到不同本地端口
mixed-port: 7890
# ...多开实例或用 listen-port 段分别绑定节点
```

然后：

```
# proxies.txt
127.0.0.1:7891
127.0.0.1:7892
...
```

```bat
pool.bat import accounts.txt --proxy-file proxies.txt --yes
```

### 方式 2：购买的静态住宅代理

```
socks5://user:pass@1.2.3.4:1080
http://user:pass@5.6.7.8:8080
```

> 注意：本 Skill 的导入脚本对 `host:port` 与 `socks5://...` 都能写进 VirtualBrowser
> （`protocol` 取 `HTTP`/`SOCKS5`）。要确认代理生效，在窗口里访问
> <https://browserleaks.com/ip> 检查出口 IP。

### 方式 3：给已有环境批量换代理

VirtualBrowser API 支持直接改：

```bash
curl -X POST http://127.0.0.1:9000/api/updateBrowser \
  -H "Content-Type: application/json" \
  -d '{"id":7,"proxy":{"mode":1,"protocol":"SOCKS5","host":"1.2.3.4","port":"1080","user":"u","pass":"p"}}'
```

改完**重启该窗口**生效；`pool.bat sync` 会把新代理同步进数据库。

---

## 备份与迁移

| 要备份的东西 | 位置 | 说明 |
|---|---|---|
| 任务/号池数据库 | `<FPB_ROOT>\data\fpbrowser.db` | 含窗口绑定与长 token |
| 指纹环境（含登录态） | `%LOCALAPPDATA%\VirtualBrowser\Workers\<id>` | 体积大；只迁 token 方案时可不迁 |
| 环境清单 | `%LOCALAPPDATA%\VirtualBrowser\User Data\virtual.dat` | 环境定义（代理/指纹配置） |
| 本 Skill 配置 | 环境变量与 `setting.toml` | 手工记录 |

只迁「token 方案」的最小集合：`fpbrowser.db` + `virtual.dat` + `Workers/`（可选）。
换机后：装好三个组件 → 打补丁 → 覆盖 `virtual.dat` → 跑 `pool.bat sync` → `pool.bat doctor`。

---

## 性能与稳定性调优

| 项 | 建议 | 原因 |
|---|---|---|
| 单窗口并发 | 1 | 插件按窗口串行处理任务，并发 >1 容易互相干扰 |
| 池总并发 | ≤ 窗口数 | 超过就会被排队，意义不大 |
| 同窗口冷却 | 20–30s | 太快易触发风控 |
| `connect_wait_seconds` | 30（慢机器 60） | 冷启动等待 |
| 窗口回收 | 长跑后 `pool.bat stop` 再 `start` | 释放内存碎片 |
| 定期清理缓存 | `POST :9000/api/clearCache {"id":N}` | **保留登录态**，只清 HTTP/GPU 缓存 |

---

## 安全

- `accounts.txt`、`*.db`、`logs/` 已在 `.gitignore`；**永远不要提交**
- `pool.bat status` / `doctor` 只显示邮箱与「token 有无+到期」，不打印 token 原文（保持这个习惯）
- 后台 `admin/admin` 请改密码；对外暴露端口时务必换 `api_key` 并加访问控制
- 跨机部署（指纹浏览器在另一台机器）时：`[extension_executor].base_url` 填网关局域网 IP，
  且两端防火墙放行插件 WS 端口
