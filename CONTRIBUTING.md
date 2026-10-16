# 贡献指南

感谢愿意一起完善这个号池工具包。请先读下面的约束 —— 每一条都来自真实踩坑，
不遵守会引入很难查的偶发问题。

## 提交前自查

```bat
pool.bat setup                                           :: 幂等，应全部 ✅
pool.bat doctor                                          :: 应全绿（30+ 项）
pool.bat test                                            :: 真出一张图
python -m pytest tests\ -q                               :: 43 个离线单测
python -m ruff check scripts\ tests\                     :: 静态检查
python scripts\lint_bat.py                               :: .bat 静态检查（改了 .bat 必跑）
python scripts\scan_secrets.py                           :: 凭据扫描（**必跑，绝对不许带真实卡密/密钥**）
python scripts\apply_patches.py --validate               :: 改了补丁必跑
```

CI（`.github/workflows/ci.yml`）会在 Python 3.10/3.11/3.12 上重跑以上全部项，
外加一个「无服务时 CLI 要友好报错」的冒烟作业 —— 本地过不了就不用提 PR。

## 硬性规范

1. **脚本零硬编码路径**：新脚本必须 `from _common import Paths` 取路径，
   不要出现 `D:\fpbrowser2api` 这类字面量（文档与示例除外）。
2. **`.bat` 一律 ASCII + CRLF**：cmd 解析 UTF-8 批处理会错位吃掉行首字符
   （表现为 `'xxx' 不是内部或外部命令`）。中文提示交给 Python 打印。
   **括号块（`if ... (`）内的 `echo` 不能含未转义的 `(` `)`**——一个多余的 `)` 会提前结束块，
   让块后面的命令（如 `pause`）**无条件执行**，症状极难定位（本节这条就是踩出来的）。
   改完 .bat 必须跑：`python scripts\lint_bat.py`（doctor 第 9 节也会自动检查）。
3. **不要用 `pause` 做交互**：会让脚本化/Agent 调用卡死。只有「双击菜单」和
   「Python 缺失」两条路径才允许 pause。
3. **`for /f ('...')` 内部不要用带引号的可执行全路径**：首字符是引号会让 cmd 剥引号，
   报「文件名、目录名或卷标语法不正确」。
4. **不要用 `wmic`**：Windows 11 24H2（build 26200+）已移除；改用
   `Get-CimInstance Win32_Process` 或 `tasklist`。
5. **外部命令写全路径**（例如 `%SystemRoot%\System32\find.exe`），
   否则可能被 PATH 里 Git/MSYS 的同名程序顶替（`find` 就是典型受害者）。
6. **改上游代码只能通过 `patches/`**：改完重新生成补丁，并在 `patches/README.md`
   写清「上游行为 → 现在行为 → 为什么」。补丁要能用内置应用器（`pool.bat patch`）干净应用。
7. **写数据库前必须备份**，且只做幂等 upsert（按邮箱/主键去重）。
8. **不要打印敏感信息**：token 只显示「有/无 + 到期」；密码永不打印；示例文件用假数据。
9. **错误信息必须带「下一步做什么」**：新增错误处理时，用 `gen_image.diagnose()` 同一思路，
   把「现象 → 修法」写进提示，而不是只抛堆栈。

## 文档规范

- 每条命令都要**可复制执行**，并写清「验证方式」（怎么判断成功）。
- 报错信息用反引号原样引用，便于搜索。
- 新发现的坑要同时更新 `docs/07-troubleshooting.md` 和 `README.md` 的快查表。
- 新增脚本文档时，说明它**解决什么问题**，而不只是参数列表。
- **文档里的示例一律脱敏**：账号用 `demo_user01@example.com`，密钥用 `YOUR_...`，
  内网地址用 `192.168.1.100`。`scan_secrets.py` 会拦截漏网之鱼（测试夹具可用
  `# scan-secrets:allow` 显式豁免）。
- 中英双语的对应关系：`README.md`（中文）与 `README.en.md`（English）改了其中一个，
  请同步另一个（只改一边也可以接受，但请在 PR 里说明）。

## 提交信息

约定式提交：`feat:` / `fix:` / `docs:` / `chore:` / `refactor:`。
涉及上游改动的，正文写清「上游行为 → 现在行为 → 影响」。

## PR 描述清单

- [ ] `pool.bat doctor` 全绿
- [ ] `gen_image.py` 能出一张 > 100 KB 的 PNG
- [ ] 改动过的路径在「没有 venv / 换盘符」时仍能自动探测或给出清晰报错
- [ ] 没有引入明文凭据
- [ ] 新坑已写进排错文档
