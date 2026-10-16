# 02 · 安装

> 目标：把三个组件装好并打好补丁。全程约 20 分钟（不含下载 VirtualBrowser）。
>
> ⚡ **偷懒路线（推荐）**：装好 VirtualBrowser 客户端 + Python 后，直接跑
> `pool.bat setup`——它会自动完成下面第 3/4/6 节的全部工作（含克隆代码、建 venv、装依赖、打补丁、写配置、装扩展、起服务、建空间）。
> 失败会逐条告诉你「→ 怎么修」，修完重跑同样命令即可（幂等）。
> 下面的手写步骤适合想完全掌控、或 `setup` 自动探测失败时对照排查。

## 0. 组件清单

| 组件 | 从哪来 | 放哪 |
|---|---|---|
| VirtualBrowser 客户端 | 官网 [virtualbrowser.cc](https://virtualbrowser.cc) / [vbbrowser.com](https://www.vbbrowser.com/) | 默认 `C:\Program Files\VirtualBrowser` 或自定义（本 Skill 示例用 `D:\VirtualBrowser`） |
| VirtualBrowser 本地 API（免 VIP） | `git clone https://github.com/yang0/VirtualBrowser` → 用 `api_server/` | 示例 `D:\VirtualBrowser-src\api_server` |
| 调度网关 | `git clone https://github.com/yang0/fpbrowser2api` | 示例 `D:\fpbrowser2api` |
| 本 Skill | 当前目录 | 示例 `D:\生图号池搭建skill` |

> VirtualBrowser 客户端自带付费的本地 API；本方案用的是开源的 `api_server`，
> **不依赖客户端 VIP**（客户端仍然要装，因为内核与 profile 由它提供）。

## 1. Python

装 **Python 3.11**（3.10/3.12 也可，3.11 验证最充分）：<https://www.python.org/downloads/>

- 安装时勾选 **Add python.exe to PATH**
- 验证：

```bat
py -0p            :: 列出已安装版本
py -3.11 -V
```

## 2. VirtualBrowser 客户端

1. 官网下载安装（或 `VirtualBrowser.Setup.x.exe`）
2. 打开客户端 → 左侧「API」→ 确认已开启本地 API（记下端口，默认 `9000`）
   - 若客户端没有该菜单，用下面的开源 `api_server` 替代即可
3. 关闭客户端（首次安装后可以先开着，用来确认没有环境残留）

## 3. VirtualBrowser 本地 API（api_server）

```bat
git clone https://github.com/yang0/VirtualBrowser.git D:\VirtualBrowser-src
cd /d D:\VirtualBrowser-src\api_server
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" playwright mcp
```

### 3.1 内核路径

`api_server` 需要知道 VirtualBrowser 的 **Chromium 内核**（不是 Electron 外壳）在哪：

```
<安装目录>\VirtualBrowser\<版本号>\VirtualBrowser.exe      ← 这个才是内核
<安装目录>\VirtualBrowser.exe                             ← 这是 Electron 外壳，别指它
```

补丁已支持自动探测常见位置；自定义目录用环境变量显式指定：

```bat
setx VB_BROWSER_EXE "D:\VirtualBrowser\VirtualBrowser\151.0.7922.47\VirtualBrowser.exe"
```

> 判定标准：同一目录里存在 `chrome.dll` 或 `chromedriver.exe`。

### 3.2 打补丁

```bat
cd /d D:\VirtualBrowser-src
git apply -p1 -C1 --ignore-whitespace "D:\生图号池搭建skill\patches\01-virtualbrowser-api_server.patch"
```

补丁做了 6 件事（详见 [../patches/README.md](../patches/README.md)）：
内核路径探测、**wmic→PowerShell CIM**（新系统必须）、启动失败自动清理+重试、
补 3 个 FPBrowser2API 需要的接口、可选 MCP 依赖、CRLF 说明。

### 3.3 启动

```bat
cd /d D:\VirtualBrowser-src\api_server
.venv\Scripts\python.exe server.py
```

浏览器打开 <http://127.0.0.1:9000/docs> 应看到 Swagger。
（用本 Skill 时不需要手动起，`pool.bat start` 会后台拉起。）

## 4. FPBrowser2API（调度网关）

```bat
git clone https://github.com/yang0/fpbrowser2api.git D:\fpbrowser2api
cd /d D:\fpbrowser2api
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果 `requirements.txt` 有装不上的 pin：

```bat
.venv\Scripts\python.exe -m pip install fastapi uvicorn[standard] aiosqlite pydantic tomli bcrypt python-multipart httpx playwright
```

### 4.1 打补丁

```bat
cd /d D:\fpbrowser2api
git apply -p1 -C1 --ignore-whitespace "D:\生图号池搭建skill\patches\02-fpbrowser2api.patch"
```

补丁做了 5 件事：窗口同步同空间判定、窗口字段映射（备注/账号/主页）、
插件连接等待可配置、结果图 token 下载+校验、`_gpt_extension_connect_wait` 读取全局默认。

### 4.2 首次启动生成数据库

```bat
cd /d D:\fpbrowser2api
.venv\Scripts\python.exe main.py
```

首次启动会创建 `data/fpbrowser.db` 并在管理后台提供默认账号 **admin / admin**。

## 5. 本 Skill 的自检

```bat
cd /d D:\生图号池搭建skill
pool.bat doctor
```

`doctor` 会告诉你还差什么。预期的「绿色」清单：

```
[OK] Python 版本满足要求（>=3.10）
[OK] 已定位 FPBrowser2API / VirtualBrowser api_server / 数据库 / venv
[OK] 9 处补丁全部命中
[OK] 两个服务端口已监听且接口可用
[OK] 内核可执行文件存在
[OK] 已注册插件：FPBrowser2API Bridge
[OK] 任务池绑定 N 条 / 带 token N 条 / token 有效期正常
```

## 6. 注册浏览器插件

```bat
xcopy /E /I /Y "D:\fpbrowser2api\browser_extension" "D:\VirtualBrowser\extensions\fp_browser_extension"

curl -X POST http://127.0.0.1:9000/api/addCrx ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"D:/VirtualBrowser/extensions/fp_browser_extension\",\"name\":\"FPBrowser2API Bridge\"}"

curl http://127.0.0.1:9000/api/getCrxList
```

要点：

- 路径必须**长期稳定**（换目录后要重新注册），用正斜杠或双反斜杠
- 注册后**新启动**的窗口才会带上插件（已开着的窗口要重启）
- 插件会注入到每个窗口，无需在客户端里逐个安装

## 7. 常见安装问题

| 现象 | 处理 |
|---|---|
| `ModuleNotFoundError: mcp.server.fastmcp` | `mcp` 装成了 2.x；补丁已容错，或 `pip install "mcp<2"` |
| `未找到 VirtualBrowser Chromium 内核执行程序` | 设 `VB_BROWSER_EXE` 指向 `<...>\<版本>\VirtualBrowser.exe` |
| 端口被占用 | 改 `setting.toml [server].port` 与 `VB_API_PORT` |
| `git apply` 报 whitespace/CRLF 错误 | 加 `-C1 --ignore-whitespace`；或用内置应用器 `pool.bat patch`；或按 patches/README.md 手动改 |
| 服务起不来但没报错 | 看 `logs\*.err.log`（`pool.bat logs`）；多半是依赖或端口 |

装好之后 → [QUICKSTART.md](QUICKSTART.md) 继续第 4 步（配置与建池）。
