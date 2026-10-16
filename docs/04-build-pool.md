# 04 · 建号池（两条路 + 预热）

> 前置：空间/浏览器/任务类型要先存在。没建过就直接跑 `pool.bat setup`（会自动建好）；
> 本节只关心「窗口 + 账号 + token」怎么进来。

## 先判断你的卡密属于哪种

| 卡密内容 | 段数 | 走哪条路 | 优点 | 代价 |
|---|---|---|---|---|
| `邮箱----密码----2FA----access_token` | 4 段 | ✅ **长 token 直灌**（本 Skill） | 不登录网页，绕过 Cloudflare/验证码/2FA；建 20 号约 3 分钟 | token 会过期（7–10 天），需重导 |
| `邮箱----密码----2FA` | 3 段 | 浏览器自动登录（上游 `batch_bind_chatgpt.py`） | 有真实 Cookie 会话，token 可自动刷新 | 单号 1–2 分钟，可能被 Cloudflare/邮箱验证码挡住 |

> 两者不冲突：先 token 直灌把池跑起来，之后需要「更长寿命会话」时再对个别号补一次真实登录。
>
> 💡 **想从零开始、连命令都不想记？** 双击 `pool.bat` → 选 `4`（导入卡密），它会一步步问你要文件路径。

---

## 路线 A：长 token 直灌（推荐）

### A1. 准备卡密文件

```
# accounts.txt（# 开头为注释，空行忽略）
邮箱----密码----2FA密钥----access_token
demo_user01@example.com----Passw0rd!A----JBSWY3DPEHPK3PXP----eyJhbGciOiJSUzI1NiIs...
demo_user02@example.com----Passw0rd!B----KRSXG5CTMVRXEZLU----eyJhbGciOiJSUzI1NiIs...
```

分隔符支持 `----`（四连字符）与 `——`（中文长横线）；顺序不能变。

> ⚠️ 真实卡密属于敏感凭据：不要贴进聊天记录、不要提交到仓库。
> `accounts.txt` 已在 `.gitignore` 里。

### A2. 先导 1 个，跑通再全量

```bat
pool.bat import accounts.txt --only 1 --yes
```

脚本会打印（下面是示例输出，账号已脱敏）：

```
[1/5] 校验 token（直连 ChatGPT 接口）...
      [OK  ] demo_user01@example.com  plan=free  到期 2026-10-26 11:51:08
[2/5] 准备 VirtualBrowser 环境 ...
      ChatGPT-Worker-01  环境ID=1  demo_user01@example.com  代理=直连
[3/5] 同步窗口 ...   同步完成，写入/更新 1 条窗口记录
[4/5] 写入账号 / 窗口绑定 / 任务池 token（1 条）  已备份 fpbrowser.bak-....db
[5/5] 复核 ...       任务类型 6 窗口池共 1 条
```

然后立刻验证一张图：

```bat
pool.bat gen "测试：一只柴犬宇航员" -o out\_smoke.png
```

### A3. 全量导入

```bat
pool.bat import accounts.txt --yes
```

**幂等**：按邮箱 upsert，重复执行不会重复建环境，只会刷新 token 与绑定。

### A4. 换新卡密（token 过期时）

```bat
pool.bat import accounts_new.txt --no-create-envs --yes
```

`--no-create-envs` 表示按 **备注里的邮箱** 匹配已有环境（不新建），
适合「号还是这些号，只是 token 续期」。

### A5. 每个窗口一个独立代理（强烈建议）

`proxies.txt`（每行一个，按顺序对应卡密顺序）：

```
127.0.0.1:7891
127.0.0.1:7892
socks5://user:pass@1.2.3.4:1080
```

```bat
pool.bat import accounts.txt --proxy-file proxies.txt --yes
```

> 20 个账号共用 1 个出口 IP 有联动风控风险；代理池搭建见
> [06-operations.md](06-operations.md#代理分配)。

### A6. 导入脚本干了什么（对照数据库）

| 步骤 | 动作 | 表/字段 |
|---|---|---|
| 1 | 校验 token（`GET /backend-api/me` 200） | 无（只校验） |
| 2 | 建/复用指纹环境（名 `ChatGPT-Worker-NN`，**备注=邮箱**） | VirtualBrowser `virtual.dat` |
| 3 | 清理失效窗口 + 同步远端窗口 | `windows` |
| 4 | 写账号资料 | `platform_accounts`(platform_username/password/efa) |
| 5 | 窗口 ↔ 账号互相绑定 | `windows.platform_account_id` / `platform_account` / `window_remark` |
| 6 | 绑任务池 + 写长 token | `task_type_windows`(enabled, remaining_quota, **sora_access_token**, sora_access_expires) |

写库前自动备份 `data/fpbrowser.db → fpbrowser.bak-<时间戳>.db`。

---

## 路线 B：账号密码自动登录（无 token 的卡密）

```bat
cd /d D:\fpbrowser2api
.venv\Scripts\python.exe scripts\batch_bind_chatgpt.py ^
  -f accounts.txt ^
  --prefix ChatGPT-Worker ^
  --proxy 127.0.0.1:7891 ^
  --vb-url http://127.0.0.1:9000 ^
  --sync-fpb --fpb-url http://127.0.0.1:8002 --space-pk 5 --task-type-id 6
```

它会：建环境 → 启动窗口 → 打开 `chatgpt.com/auth/login` → 填邮箱/密码/TOTP →
校验 `session-token` → **优雅断开 CDP 让 SQLite WAL 落盘**（登录态固化）→ 关窗 → 同步窗口。

> 首次跑建议只导 1 个（把 `accounts.txt` 里只留一行）确认选择器没被前端改版影响。
> 被 Cloudflare 挡住时：换代理、降低频率、或改走路线 A。

---

## 为什么要预热（新池必做一次）

```bat
pool.bat warm
```

两个必预热的理由（都是实测踩出来的）：

### 1) 插件配置存在窗口 profile 里

插件注册需要的 `fpb_space_id / fpb_window_key / fpb_bridge_url` 是**写进该窗口的
`chrome.storage.local`** 的。全新窗口第一次启动时：

```
Chromium 冷启动(3–8s) + 扩展 service worker 初始化 + 中转页加载
```
可能超过任务侧等待时间，任务直接失败：

```
浏览器插件未连接：space_id='default' window_key='N'
```

预热 = 主动把这段「首次连接」跑完，配置持久化；之后窗口每次启动插件自动重连。

### 2) 全新 profile 没访问过 chatgpt.com

首次访问才会拿到 Cookie / `cf_clearance`。没这一步，插件在页面上下文 fetch 会返回空：

```
GPT pageFetch returned empty result for https://chatgpt.com/backend-api/f/conversation
```

预热脚本会在注册成功后**再访问一次目标站**并停留数秒。

### 实测效果

| 阶段 | 6 并发任务成功率 |
|---|---|
| 未预热 | 2/6 |
| 预热后 | **6/6**（总耗时 83s） |

### 预热用法

```bat
pool.bat warm                  :: 全池
pool.bat warm --keys 6,16      :: 只补失败的
pool.bat warm --keep-open      :: 预热后不关窗口（想看效果时用）
pool.bat warm --visit ""       :: 只连插件，不访问目标站
```

失败窗口直接重跑即可（脚本已处理「窗口已开着导致启动失败」的重试）。

---

## 建池后的验收清单

```bat
pool.bat doctor
pool.bat status
pool.bat gen "验收：一只柴犬宇航员" -o out\_acceptance.png
```

- [ ] `doctor` 第 7 节：窗口池绑定数 = 账号数，token 全部有效
- [ ] `status` 能看到每个窗口的额度与到期时间
- [ ] 出图 PNG **> 100 KB**
- [ ] （可选）`pool.bat batch examples\prompts.txt --concurrency 4` 全部成功
