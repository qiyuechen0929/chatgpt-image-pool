# 08 · 常见问题（FAQ）

## 原理类

**Q1：为什么可以不让浏览器登录就出图？**
A：ChatGPT 出图接口接受 `Authorization: Bearer <access_token>`。卡密里的第 4 段就是长 token，
本项目的 `gpt_workflow` 会优先使用窗口池里缓存的 `task_type_windows.sora_access_token`，
只有它缺失/过期时才回落到浏览器会话。所以把 token 写进 DB 即可，窗口不需要登录态。

**Q2：那浏览器窗口到底起什么作用？**
A：它是**请求的真实发起点**：插件在 `chatgpt.com` 页面上下文里 fetch，
带着独立指纹、Cookie、代理，能过 CDN/风控校验；同时提供隔离（一号一环境）。

**Q3：为什么不直接用 requests 调接口？**
A：会缺少浏览器指纹/上下文，Cloudflare 与风控更容易拦；也无法复用每个号的独立出口 IP。

**Q4：token 多久过期？**
A：看 JWT 的 `exp`。常见 7–10 天。`pool.bat doctor` / `status` 会显示到期时间与预警。

**Q5：会不会封号？**
A：任何自动化都有风险。降低风险的手段：一窗口一独立代理、控制频率、开启任务冷却、
不要短时间大量重复同一提示词。本项目不承诺规避风控。

---

## 使用类

**Q5.5：我完全不懂命令行，能用吗？**
A：能。双击本目录的 `pool.bat` → 出现中文菜单 → 按数字。第一次选 `9`（一键搭建），
之后选 `4`（导入卡密）/ `5`（预热）/ `8`（自检）/ `6`（出图）即可。
详细的“每一步应该看到什么”看 [00-新手必读.md](00-新手必读.md)。

**Q5.6：能让 AI 助手替我搭/替我出图吗？**
A：能。`pool.bat install-skill` 把本 Skill 装到 `~/.agents/skills/chatgpt-image-pool`，
之后在任意 AI 会话里说“用 chatgpt-image-pool 搭一个生图号池 / 出一张图：……”即可。
所有关键命令都支持 `--json`，Agent 可以可靠地读结果（失败时带 `hint` 字段说明下一步）。

**Q5.7：一键搭建（`pool.bat setup`）报错了怎么办？**
A：它每一条失败下面都有 `→ 怎么修`，改完**再跑一次同样命令**即可（幂等，不会重复建）。
看不出所以然就 `pool.bat doctor`（30+ 项体检）或 `pool.bat logs --errors`。

**Q6：一次要跑多少并发？**
A：单窗口 1 并发；池并发 ≤ 窗口数。20 窗口 / 32GB 内存实测 6–10 并发稳定。

**Q7：一张图多久？**
A：免费号常见 30–90s。批量并发时总耗时 ≈ (张数 / 并发) × 单张时间。

**Q8：每天能出多少张？**
A：取决于账号额度（免费号约 20–25 张/天/号，站点策略会变）。
`pool.bat status` 的 `remaining_quota` 列可观察。

**Q9：结果图能直接给用户 URL 吗？**
A：默认不行（内部鉴权链接，第三方打不开）。要么由你的服务带 token 下载后转存，
要么开启 `[r2]`/`[oss]` 对象存储上传得到公网直链。

**Q10：可以同时跑视频模型（veo / seedance）吗？**
A：架构支持（同一套窗口池 + 插件机制），但那些是 Google Flow / 即梦的工作流，
需要对应站点已登录的窗口；本 Skill 的脚本聚焦 ChatGPT 图片。

**Q11：换电脑怎么迁移？**
A：见 [06-operations.md#备份与迁移](06-operations.md#备份与迁移)。最小方案：
`fpbrowser.db` + `virtual.dat`（+ 可选 `Workers/`）。

**Q12：能不能不要 VirtualBrowser，用别的指纹浏览器？**
A：FPBrowser2API 也支持 RoxyBrowser（`vendor=roxy`）。但本 Skill 的脚本与补丁是针对
VirtualBrowser 的 REST API 写的；换浏览器需要另写适配层。

---

## 运维类

**Q13：服务会不会自己挂？**
A：本 Skill 的服务是后台无窗口（`DETACHED_PROCESS`）运行的，不会被误关；
但机器重启后不会自动起——需要时用任务计划程序挂 `pool.bat start`。

**Q14：窗口要不要一直开着？**
A：不需要。任务会按需启动窗口；空闲窗口会自动回收（上游 idle-close 逻辑）。
但 token 方案下**建议保留新池预热后的 profile**（配置在里面，删了要重新预热）。

**Q15：能清缓存吗？会掉登录态吗？**
A：`POST :9000/api/clearCache {"id":N}` 只清 HTTP/GPU 缓存，**保留 Cookie / localStorage**，
不影响 token 方案，也不影响已登录窗口。

**Q16：数据库能随便改吗？**
A：可以，但改前先备份。后台页面能改的尽量用后台（有校验）。
`task_type_windows.sora_access_token` / `sora_access_expires` 是最常手工调的两个列。

---

## 合规类

**Q17：能商用吗？**
A：代码是 MIT，可商用。但**账号来源与目标站点条款由使用者自负**：
只用自有/已授权账号，遵守站点 ToS 与当地法律。

**Q18：可以开源/二次分发这个 Skill 吗？**
A：可以（保留 LICENSE 与上游出处）。但**不要**把你自己的 `accounts.txt`、
`fpbrowser.db`、`logs/` 一起发出去（已在 `.gitignore` 中）。

**Q19：上游仓库更新了怎么办？**
A：先 `git stash`/`git pull`，再重新 `git apply --ignore-whitespace patches/*.patch`。
如果补丁冲突，按 [../patches/README.md](../patches/README.md) 的「手动改法」逐条对一遍，
然后 `pool.bat doctor` 复核第 3 节。

---

## 还没解决的？按这个顺序自助

1. `pool.bat doctor` → 按 FAIL 项处理
2. `docs/07-troubleshooting.md` → 按症状查
3. `pool.bat logs` → 看真实报错
4. 提 issue 时带上 `doctor` + `status` + `logs`（先删敏感信息）
