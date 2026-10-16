# 05 · 日常出图

三种用法：**CLI 单张** / **CLI 批量** / **HTTP API 对接系统**。

---

## A. CLI 单张

> 不确定环境是否正常？先跑一次 `pool.bat test`（端到端自检，真出一张图）。

```bat
pool.bat gen "一只戴耳机的柴犬，扁平插画风" --ratio 1:1 -o out/shiba.png
```

### 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `prompt` | 必填 | 提示词（中文/英文均可） |
| `--prompt-file` | — | 从文件读提示词（**推荐**：标题、逗号、括号、`& \| ^` 等符号在 cmd 里很容易被吃掉） |
| `-o, --output` | `output/img_<时间戳>.png` | 输出路径 |
| `-r, --ratio` | `1:1` | `1:1` `16:9` `9:16` `4:3` `3:4` |
| `--res` | `1k` | `1k` / `2k` / `4k`（对应模型 `gpt-image2-1k/2k/4k`） |
| `-s, --style` | `concept_art` | `realistic` `concept_art` `cyberpunk` `anime` `oil_painting` `product` |
| `--raw-prompt` | 关 | 不做提示词扩写，原样提交 |
| `--retries` | 2 | 模型「只回文字不画图」时的重试次数 |
| `--timeout` | 900 | 等待上限（秒） |
| `--json` | 关 | 输出机器可读 JSON（程序调用用） |
| `--fpb-url` / `--api-key` | 自动探测 | 跨机或自定义时用 |

### 典型场景

```bat
:: 产品图（2K，写实）
pool.bat gen "产品图：银色机械键盘悬浮在白色背景，柔和落地阴影" --res 2k --style product --ratio 1:1 -o out/kb.png

:: 竖版海报（9:16，赛博朋克）
pool.bat gen "雨夜霓虹街道的机械武士，电影感" --style cyberpunk --ratio 9:16 -o out/poster.png

:: 完全按自己的话（不扩写）
pool.bat gen "minimal flat illustration, a cat reading a book, pastel palette" --raw-prompt -o out/cat.png

:: 提示词含标点/特殊符号：写进文件再传，避免 cmd 吃字符
pool.bat gen --prompt-file prompt.txt --ratio 16:9 -o out/poster.png

:: 给程序调用
pool.bat gen "一只柴犬" --json -o out/x.png
```

---

## B. CLI 批量（并发）

```bat
:: prompts.txt 每行一条
pool.bat batch prompts.txt --outdir out --concurrency 4
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `prompts_file` | — | 提示词文件（`#` 注释，空行忽略） |
| `--prompt` + `-n` | — | 同一提示词出 N 张 |
| `--outdir` | `output` | 输出目录 |
| `--concurrency` | 3 | 并发数（**建议 ≤ 窗口数**） |
| `--ratio` / `--res` / `--style` | 同单张 | 对所有任务生效 |
| `--raw-prompt` | 关 | 同上 |
| `--retry-failed` | 关 | **只重跑上次报告里失败的条目**（免费号偶发失败很好用） |

> 只重跑失败的：`pool.bat batch --outdir out --retry-failed`（提示词从上次报告里取，不用重写）

产出：

```
out/001_20261016-192730.png
out/002_20261016-192730.png
out/_batch_report.json          ← 成功/失败/耗时/逐条明细
```

示例报告：

```json
{"total": 2, "ok": 2, "failed": 0, "seconds": 63,
 "items": [{"index": 1, "ok": true, "saved_path": "...", "bytes": 1304576, "attempts": 1}]}
```

**并发建议**：`concurrency = min(窗口数, 内存/0.5GB)`。20 窗口 / 32GB 内存可跑 6–10 并发。
同一窗口并发建议保持 1（`task_types.concurrency = 1`）。

---

## C. HTTP API（对接自己的系统）

### C1. 取 API Key

后台「系统配置」页面可见，或直接读数据库：

```bat
sqlite3 D:\fpbrowser2api\data\fpbrowser.db "select api_key from system_config where id=1"
```

> ⚠️ 数据库里的 key **覆盖** `setting.toml` 的 key（首次启动时写库）。

### C2. 提交任务

```bash
curl -X POST http://127.0.0.1:8002/v1/videos \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image2-1k","prompt":"一只柴犬宇航员","aspect_ratio":"1:1"}'
```

响应：

```json
{"id":"9f78...","task_id":"9f78...","status":"queued","model":"gpt-image2-1k","progress":0}
```

**图片模型的 duration 规则**（容易踩）：

| 传法 | 结果 |
|---|---|
| 不传 `duration`/`seconds` | ✅ 服务端自动置 `seconds=4` |
| 传 `duration=4` 或 `seconds=4` | ✅ 允许 |
| 传其它值（如 `1`、`8`） | ❌ HTTP 400 `must set duration=4` |

### C3. 轮询

```bash
curl http://127.0.0.1:8002/v1/videos/<task_id> -H "Authorization: Bearer <API_KEY>"
```

状态机：`queued → processing → completed | failed`（终态带 `final: true`）。
完成后：

```json
{"status":"completed","image_url":"https://chatgpt.com/backend-api/estuary/content?id=file_...",
 "metadata":{"result_urls":["https://..."]},"success":true,"final":true}
```

### C4. 取回图片（关键）

`image_url` 是 ChatGPT **内部鉴权链接**，直接下载会：

```json
{"detail":"File stream access denied."}
```

三种正确取法：

| 方式 | 说明 |
|---|---|
| ✅ 用跑该任务的窗口 token | `Authorization: Bearer <task_type_windows.sora_access_token>`（本 Skill 的 `gen_image.py` 自动做） |
| ✅ 开启对象存储上传 | `setting.toml [r2]` 或 `[oss]` → 结果变公网直链 |
| ✅ 在已登录的浏览器上下文里 fetch | 仅当该窗口真的登录了 ChatGPT |

最小 Python 示例（自带 token 下载）：

```python
import json, sqlite3, urllib.request
task_id = "9f78..."
conn = sqlite3.connect(r"D:\fpbrowser2api\data\fpbrowser.db")
row = conn.execute("""
    SELECT tc.sora_access_token FROM tasks t
    JOIN task_type_windows tc ON tc.window_pk = t.window_pk
    WHERE t.task_id = ? LIMIT 1""", (task_id,)).fetchone()
img = json.loads(conn.execute("SELECT result_json FROM tasks WHERE task_id=?", (task_id,)).fetchone()[0])
url = img["result_urls"][0]
req = urllib.request.Request(url, headers={
    "Authorization": "Bearer " + row[0],
    "Origin": "https://chatgpt.com", "Referer": "https://chatgpt.com/",
    "User-Agent": "Mozilla/5.0"})
open("out.png", "wb").write(urllib.request.urlopen(req, timeout=120).read())
```

### C5. 支持的模型

| 模型 | 输出 | 说明 |
|---|---|---|
| `gpt-image2-1k` / `2k` / `4k` | 图片 | ChatGPT gpt-image-2，本号池主用途 |
| `gpt-image2-*-_sync` | 图片 | 同步变体（按上游实现） |
| `veo-3-1` / `veo-omni-flash*` | 视频 | 需 Google Flow 窗口（不属本 Skill 范围） |
| `nana-banana-*` / `seedance-*` | 图/视频 | 同上 |

`GET /v1/models` 可查当前实例支持的完整清单。

---

## D. 一个任务的“健康”标准

| 指标 | 正常 | 异常 |
|---|---|---|
| 单张耗时 | 30–90s | > 300s（可能卡住，检查窗口） |
| PNG 大小 | 1–3 MB | < 100 KB（多为错误 JSON；用 `gen_image.py` 下载） |
| 成功率 | ≥ 90%（预热后） | 连续失败 → 看 `pool.bat status` 的冷却与错误消息 |
| 额度 | 每号 20–25 张/天（免费号，随站点策略变化） | 归零 → 换号或等重置 |

批量跑完后建议看一眼 `_batch_report.json` 的失败明细（会带 `error` 原文）。
