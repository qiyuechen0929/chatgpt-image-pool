# QUICKSTART · 从零到第一张图

> 目标：**30 分钟内**在一个干净的 Windows 上跑出第一张图。
> 每一步都有「验证方式」，过不了就别往下走。
>
> 💡 **两条路选一条**：
> - **省事（推荐）**：只需装好 VirtualBrowser 客户端 + Python，然后 `pool.bat setup` 一条命令搞定其余全部（下方 **第 1' 节**）。
> - **手动**：想搞清楚每一步在干什么 → 照 **第 1–5 节** 逐步做。

---

## 1'. 一条命令搭建（推荐）

```bat
pool.bat setup          :: 自动：建 venv/装依赖/打补丁/写配置/装扩展/起服务/建空间/自检
```

- 结尾看到 `✅` 列表 且最后一行是「下一步（复制即用）」= 成功。
- 看到 `❌` 就照它下面的 `→` 做完，**再跑一次同样命令**（幂等）。
- **验证**：`pool.bat doctor` → 结尾「全部通过 ✅」。
- 不想自动克隆代码：加 `--no-clone`；只想装环境不起服务：`--skip-start`。

然后直接跳到 **第 6 节（导入卡密）**。

---

## 0. 你需要准备

| 东西 | 说明 |
|---|---|
| Windows 10/11 | VirtualBrowser 只有 Windows 客户端 |
| Python 3.11 | [python.org](https://www.python.org/downloads/) 安装时勾选 *Add to PATH* |
| VirtualBrowser 客户端 | [virtualbrowser.cc](https://virtualbrowser.cc) / [vbbrowser.com](https://www.vbbrowser.com/) |
| VirtualBrowser 本地 API（免 VIP） | `git clone https://github.com/yang0/VirtualBrowser` → 用其中的 `api_server/` |
| 调度网关 | `git clone https://github.com/yang0/fpbrowser2api` |
| 本 Skill | 当前目录（`生图号池搭建skill`） |
| ChatGPT 卡密 | 格式 `邮箱----密码----2FA----access_token` |

建议目录布局（脚本会自动探测，不强制）：

```
D:\
├── VirtualBrowser\        ← 客户端安装目录（含 VirtualBrowser.exe）
├── VirtualBrowser-src\    ← git clone 的仓库（含 api_server\）
├── fpbrowser2api\         ← git clone 的仓库
└── 生图号池搭建skill\      ← 本 Skill
```

---

## 1. 装依赖

```bat
:: 1.1 VirtualBrowser 本地 API 的依赖
cd /d D:\VirtualBrowser-src\api_server
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" playwright mcp

:: 1.2 调度网关的依赖
cd /d D:\fpbrowser2api
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**验证**：两条命令都不报错。若 `requirements.txt` 里有装不上的包（比如某些 pin 版本），
去掉版本号再装即可（`pip install fastapi uvicorn aiosqlite pydantic tomli bcrypt python-multipart httpx playwright`）。

---

## 2. 打补丁（关键一步）

上游代码有 9 处必须改造，否则会踩到「内核找不到 / 窗口启动即退出 / 窗口同步永远被跳过 / 结果图下载 403」等坑。
每处改动的原因写在 [../patches/README.md](../patches/README.md)。

```bat
:: 2.1 VirtualBrowser api_server
cd /d D:\VirtualBrowser-src
git apply --ignore-whitespace "D:\生图号池搭建skill\patches\01-virtualbrowser-api_server.patch"

:: 2.2 FPBrowser2API
cd /d D:\fpbrowser2api
git apply --ignore-whitespace "D:\生图号池搭建skill\patches\02-fpbrowser2api.patch"
```

> 没有 git？用 `patch -p1 < xxx.patch`，或照着 patches/README.md 手动改（只有 9 处）。

**验证**：

```bat
cd /d D:\生图号池搭建skill
pool.bat doctor
```

看第 3 节「上游补丁是否已打」是否全绿（补丁没打全时它会逐个列出缺哪一处）。

---

## 3. 配置

### 3.1 调度网关 `D:\fpbrowser2api\config\setting.toml`

```toml
[server]
host = "0.0.0.0"
port = 8002                       # 记住这个端口，后面都用它

[global]
api_key = "改成你自己的密钥"        # 对外调用用的 Key（首次启动会写入数据库）

[extension_executor]
enabled = true                     # 必须 true：任务走浏览器插件长连接
base_url = "127.0.0.1:8002"        # 与 [server].port 一致
bridge_token = "fpb-bridge-secret" # 插件连接鉴权（留空=不校验）
connect_wait_seconds = 30          # 新池冷启动等待（补丁新增项）
task_timeout_seconds = 1800
```

### 3.2 VirtualBrowser 本地 API

无需配置文件，用环境变量即可：

| 变量 | 用途 |
|---|---|
| `VB_API_PORT` | 本地 API 端口（默认 9000） |
| `VB_BROWSER_EXE` | 指定内核可执行文件（自动探测失败时用） |
| `VB_TAKEOVER_EXTERNAL_WINDOW=0` | 关闭「自动接管客户端手工启动的窗口」 |

**验证**：`pool.bat start` 后 `pool.bat status` 能看到两个服务 `[OK]`。

---

## 4. 注册浏览器插件（每个窗口的“耳朵”）

插件在 `D:\fpbrowser2api\browser_extension`，需要注册到 VirtualBrowser，让它给**每个窗口**注入：

```bat
:: 4.1 建议复制到稳定目录（别放在会被清理的临时目录）
xcopy /E /I /Y "D:\fpbrowser2api\browser_extension" "D:\VirtualBrowser\extensions\fp_browser_extension"

:: 4.2 注册
curl -X POST http://127.0.0.1:9000/api/addCrx ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"D:/VirtualBrowser/extensions/fp_browser_extension\",\"name\":\"FPBrowser2API Bridge\"}"

:: 4.3 确认
curl http://127.0.0.1:9000/api/getCrxList
```

**验证**：返回的 `data` 里能看到 `FPBrowser2API Bridge`，且路径真实存在
（`doctor` 第 6 节也会检查）。

---

## 5. 建号池

### 5.1 准备卡密文件

新建 `accounts.txt`（可参考 [../examples/accounts.example.txt](../examples/accounts.example.txt)）：

```
邮箱----密码----2FA密钥----access_token
demo@example.com----Passw0rd!----ABCDEFGHIJKLMNOP----eyJhbGciOiJSUzI1NiIs...
```

### 5.2 导入（先 1 个验证）

```bat
cd /d D:\生图号池搭建skill
pool.bat import accounts.txt --only 1 --yes
```

**验证**：输出里能看到 `[OK] ... 到期 2026-xx-xx`（token 校验通过）+ 「窗口池共 1 条」。

### 5.3 预热（新池必做）

```bat
pool.bat warm
```

**验证**：每个窗口都显示 `OK 已注册 + 已访问目标站`。

---

## 6. 出图！

```bat
pool.bat gen "一只戴耳机的柴犬，扁平插画风" --ratio 1:1 -o out/shiba.png
```

**验证**：`out/shiba.png` 存在且 **> 100 KB**（几十 KB 以下多半是错误 JSON 被当图片存了）。

批量：

```bat
pool.bat batch examples\prompts.txt --outdir out --concurrency 4
```

---

## 7. 全量导入 + 长期运行

```bat
pool.bat import accounts.txt --yes     :: 全部账号（幂等，可反复跑）
pool.bat doctor                        :: 上线前体检，应全绿
pool.bat status                        :: 日常看板（额度 / token 到期 / 冷却）
```

日常维护三件事：

| 频率 | 动作 |
|---|---|
| 每天 | `pool.bat status` 看额度与错误冷却 |
| token 到期前 | `pool.bat import accounts_new.txt --no-create-envs --yes` |
| 换机器/重启后 | `pool.bat start` → `pool.bat doctor` |

---

## 8. 卡住了？

1. `pool.bat doctor` —— 它会指出具体哪一项不满足
2. `pool.bat logs` —— 看两个服务的日志尾部
3. [07-troubleshooting.md](07-troubleshooting.md) —— 症状对照表
4. 还是不行：把 `doctor` 输出 + `logs` 贴出来（**注意先删掉 token/密码**）
