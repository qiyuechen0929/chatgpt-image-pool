# 补丁说明（9 处改动 + 手动改法）

本目录的两个 `.patch` 是对上游仓库的必要改造。**每一处都对应一个真实踩过的坑**，
不打补丁会出现「内核找不到 / 窗口启动即退出 / 窗口同步永远被跳过 / 结果图下载 403」等问题。

```bash
# way 1（推荐，不需要 git）：内置补丁应用器
pool.bat patch            # 应用全部（已打过会自动跳过）
pool.bat patch --check    # 只检查
pool.bat patch --revert   # 还原上游代码
pool.bat patch --validate # 校验补丁自身（hunk 行数 + 凭据扫描）

# way 2：用 git（在含 api_server/ 的仓库根目录执行）
#   -C1：本仓库里有一处 hunk 故意只带“前文”上下文（原因见下方「关于密钥」），
#         git apply 默认参数会嫌上下文不够，加 -C1 即可
#   --ignore-whitespace：兼容 CRLF/LF 差异
git apply -p1 -C1 --ignore-whitespace <skill>/patches/01-virtualbrowser-api_server.patch

# FPBrowser2API（在仓库根目录执行）
git apply -p1 -C1 --ignore-whitespace <skill>/patches/02-fpbrowser2api.patch

# 复核
pool.bat doctor        # 第 3 节应 9 项全 OK
```

> 内置应用器会先备份为 `*.prepatch.bak`，定位失败时打印「期望看到什么」而不是一句 `patch failed`。
> 已用「上游原始文件 → 打补丁 → 与线上运行文件逐字节比对」验证（7 个文件）。
> 补丁基于「从 GitHub 直接 clone 的 HEAD」生成；若你用的是别处下载的压缩包，
> 可能对不上行号，按下面的「手动改法」逐条改即可（总共 9 处）。

### 关于密钥（为什么有个 hunk 没有“后文”上下文）

上游 `skills/chatgpt-image-gen/scripts/generate_image.py` 的 `--api-key` 默认值里写着一个
**可用密钥**，而它恰好紧跟在我们要改的 `--fpb-url` 行后面。如果保留标准的 3 行后文上下文，
这个密钥就会被写进补丁、进而提交进公开仓库。所以我们把那处 hunk 的**后文上下文去掉**了：

```
@@ -271,4 +342,4 @@
     parser.add_argument("--port", ...)          ← 前文上下文（3 行）
-    parser.add_argument("--fpb-url", ...:8000...)
+    parser.add_argument("--fpb-url", ...:8002...)
     （原来的下一行含真实密钥，已被剔除）
```

代价与对策：`git apply` 需要加 `-C1`（如上）；本仓库内置的应用器不受影响。
`pool.bat patch --validate` 会持续拦截这类「补丁里带凭据」的问题。

---

## 01-virtualbrowser-api_server.patch（6 处）

### ① 内核可执行文件路径探测

**问题**：`find_browser_executable()` 只写死了 `Program Files` 路径，自定义安装目录直接报
`未找到 VirtualBrowser Chromium 内核执行程序`。

**改法**：新增 `VB_BROWSER_EXE` 环境变量（最高优先级）+ `CANDIDATE_CORE_BASES` 目录扫描 +
`_looks_like_core()`（**只有含 `chrome.dll`/`chromedriver.exe` 的才是内核，Electron 外壳不算**）。

```python
def _looks_like_core(exe: Path) -> bool:
    if not exe.exists():
        return False
    parent = exe.parent
    return (parent / "chrome.dll").exists() or (parent / "chromedriver.exe").exists()
```

**验证**：`doctor` 第 2/6 节显示内核路径。

### ② 残留窗口进程检测：`wmic` → PowerShell CIM（**新系统必改**）

**问题**：Windows 11 24H2（build 26200+）**已删除 `wmic.exe`**。上游用
`wmic process where "CommandLine like '%-worker-id=N%'" get ProcessId` 检测残留内核进程，
在新系统上**永远返回空**，导致：

- 上次被强杀/客户端启动的窗口仍占着 profile 锁
- 新进程启动后 Chromium 认为「已有实例」→ 直接退出（`exit_code=0`），界面提示「请在现有的浏览器会话中打开」
- `/api/stopBrowser` 的兜底清理也一起失效

**改法**：`_list_worker_pids()` 改用 PowerShell CIM，`wmic` 仅作老系统兜底；
新增 `_kill_worker_processes()`；`do_stop_browser` 的兜底改用它。

```python
ps_cmd = ("Get-CimInstance Win32_Process -Filter \"Name='VirtualBrowser.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*--worker-id={str_id}*' }} | "
          "Select-Object -ExpandProperty ProcessId")
```

**验证**：`python -c "import core; print(core._list_worker_pids('1'))"` 能列出真实 PID。

### ③ 启动失败自动清理 + 重试

**问题**：即使检测修好了，仍可能因为历史残留锁文件失败。

**改法**：`do_launch_browser()` 的进程启动改为**最多 2 次尝试**：第一次若进程立即退出，
则结束该环境全部残留进程 → 清理 `LOCK/SingletonLock/lockfile` → 等 2s → 重试。

### ④ 补齐 FPBrowser2API 需要的 3 个接口

**问题**：FPBrowser2API 的 VirtualBrowser 适配层会调用官方 16 项清单里**没有**的接口：

| 接口 | 用途 |
|---|---|
| `GET/POST /api/isBrowserRunning?id=` | 判断窗口是否在运行（连接信息探测） |
| `POST /api/randomizeFingerprint {"id":}` | 重置指纹（只改指纹字段，保留代理/名称/分组） |
| `POST /api/clearCache {"id":}` | 清本地缓存（**保留 Cookie / LocalStorage 登录态**） |

**改法**：`core.py` 增加 `do_is_browser_running()` / `do_randomize_fingerprint()` / `do_clear_cache()`；
`server.py` 增加对应路由。

**验证**：`curl :9000/api/isBrowserRunning?id=1`。

### ⑤ MCP 依赖容错（否则服务起不来）

**问题**：`mcp` 2.x 把 `FastMCP` 改名为 `MCPServer`，上游 `from mcp_server import mcp` 在
2.x 环境下 import 失败 → **整个 REST API 服务都起不来**（很多人第一次就卡这里）。

**改法**：把 MCP 导入与挂载改为**可选**，失败只打警告，REST API 正常提供：

```python
try:
    from mcp_server import mcp as _vb_mcp
except Exception as _mcp_err:
    _vb_mcp = None
    print(f"[Warn] MCP 服务未启用（不影响 REST API）：{_mcp_err}")
```

> 需要 MCP 功能就 `pip install "mcp<2"`。

### ⑥ `.bat` 启动脚本（CRLF + venv 优先）

原 `start_api.bat` 写死 `D:\Python313\python.exe`，且文件是 LF → cmd 解析异常。
改为优先用本目录 `.venv`，并统一 **CRLF**。

---

## 02-fpbrowser2api.patch（5 处）

### ⑦ 窗口同步：同空间窗口被误判为「跨空间」而永久跳过

**问题**（`src/core/database.py` → `upsert_windows`）：

```python
# 原代码：只要 window_key 存在于任何空间就跳过
cur = await db.execute("SELECT 1 FROM windows WHERE window_key = ? AND deleted = 0 LIMIT 1", (window_key,))
```

导致**同一空间**里已存在的窗口永远得不到更新 —— 改名、换代理、换账号都同步不回来，
新号池表现为「同步完成，写入/更新 0 条窗口记录，跳过 N 个跨项目空间窗口」。

**改法**：加上空间过滤。

```python
cur = await db.execute(
    "SELECT 1 FROM windows WHERE window_key = ? AND deleted = 0 AND space_pk != ? LIMIT 1",
    (window_key, int(space_pk)),
)
```

**验证**：`pool.bat sync` 输出 `affected=N skipped=0`。

### ⑧ VirtualBrowser 窗口字段映射（后台看不到绑定账号）

**问题**：`_vb_list_windows()` 没有把 VirtualBrowser 的 `remark`（号池里存邮箱）与
`homepage` 映射出来，导致 `windows.window_remark / platform_account / platform_url` 全空，
后台无法回答「哪个窗口绑哪个号」。

**改法**：补 `window_remark`；`platform_account` 在无账号字段时回落到「remark 里含 `@`」；
`platform_url` 取 `homepage.value`。

### ⑨ 插件连接等待可配置（新池冷启动）

**问题**：`gpt_task_executor.py` 里 `extension_connect_wait_seconds` 默认写死 **10s**。
新环境首次启动：Chromium 冷启动 + 扩展 service worker 初始化 + 中转页加载，经常 > 10s，
任务直接失败：`浏览器插件未连接：space_id='default' window_key='N'`。

**改法**：新增 `_gpt_extension_connect_wait()`：先看任务 payload，再看全局配置
`[extension_executor].connect_wait_seconds`（`src/core/config.py` 新增属性，默认 **30s**，
可用 `FPB_EXTENSION_CONNECT_WAIT_SECONDS` 覆盖）。

### ⑩ 结果图下载：token 授权 + 真图校验

**问题**（`skills/chatgpt-image-gen/scripts/generate_image.py`）：
下载结果图时用「活着的窗口的 Cookie 会话」去 fetch。本方案是 **token 直灌**、窗口**没有登录 Cookie**，
于是拿到的是 33 字节错误 JSON，却仍打印：

```
[SUCCESS] 高清图片已保存: ... (大小: 0.0 KB)
```

**改法**：

1. 新增「按 task_id 反查该窗口 `sora_access_token`」并用 `Authorization: Bearer` 下载
2. 新增 `_looks_like_image()` 校验（PNG/JPEG/GIF/WEBP 魔数 + >5KB）
3. 顺序：**token 下载 → CDP（已登录窗口）→ 匿名兜底**，全部失败才报错

**验证**：`pool.bat gen "测试" -o out.png` 得到 1–3 MB 的 PNG。

---

## 手动改法速查表（不适用 patch 时）

| # | 文件 | 关键点 |
|---|---|---|
| ① | `api_server/core.py` | `CANDIDATE_EXE_PATHS`/`CANDIDATE_CORE_BASES` + `_looks_like_core()` + `VB_BROWSER_EXE` |
| ② | `api_server/core.py` | `_list_worker_pids()` 用 `Get-CimInstance Win32_Process`；`_kill_worker_processes()`；`do_stop_browser` 兜底调用它 |
| ③ | `api_server/core.py` | `do_launch_browser()` 启动循环 2 次，失败先 `_kill_worker_processes` + `cleanup_profile_locks` |
| ④ | `api_server/core.py` + `server.py` | 三个函数 + 三个路由（`/api/isBrowserRunning`、`/api/randomizeFingerprint`、`/api/clearCache`） |
| ⑤ | `api_server/server.py` | `from mcp_server import mcp` 包 `try/except`，挂载前判空 |
| ⑥ | `api_server/start_api.bat` | 用 `%~dp0.venv\Scripts\python.exe`，文件存 CRLF |
| ⑦ | `fpb/src/core/database.py` | `upsert_windows` 的重复检查加 `AND space_pk != ?` |
| ⑧ | `fpb/src/services/fp_browser_client.py` | `_vb_list_windows` 返回 `window_remark` / `platform_account` / `platform_url` |
| ⑨ | `fpb/src/core/config.py` + `src/services/gpt_task_executor.py` | 新增 `extension_connect_wait_seconds` 属性 + 3 处调用改用它 |
| ⑩ | `fpb/skills/chatgpt-image-gen/scripts/generate_image.py` | 下载块：token 优先 + 图片魔数校验 + 三级兜底 |

改完后务必：

```bat
pool.bat patch --check      :: 9 项应全部 OK
pool.bat doctor             :: 第 3 节应全绿
```

---

## 兼容性与上游更新

- 补丁基线：`yang0/VirtualBrowser` 与 `yang0/fpbrowser2api` 的 GitHub HEAD（2026-10 克隆）。
- 上游更新后：`git pull` → 重新 `git apply --ignore-whitespace patches/*.patch`。
  冲突时按上面的速查表逐条对，`doctor` 会告出哪一处没打上。
- 本 Skill 的脚本不依赖补丁的具体行号，只依赖**行为**（例如 `isBrowserRunning` 接口存在），
  所以你也可以用别的方式实现同样的行为。
