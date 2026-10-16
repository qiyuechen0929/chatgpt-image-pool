<!-- 感谢贡献！请先读 CONTRIBUTING.md（有几条硬性规范，都来自真实踩坑） -->

## 这个 PR 做了什么

<!-- 一句话说清「改了什么 + 为什么」。关联 issue：Fixes #123 -->

## 改动类型

- [ ] 🐞 Bug 修复
- [ ] ✨ 新功能
- [ ] 🩺 排错/运维改进（错误提示、诊断、日志）
- [ ] 📝 文档
- [ ] 🔧 工程化（CI / 测试 / 构建）
- [ ] ⚡ 性能 / 稳定性

## 影响范围

<!-- 勾选受影响的部分，方便 review -->
- [ ] `pool.bat` / 菜单
- [ ] `scripts/setup_pool.py`（一键搭建）
- [ ] 建池链路（import / warm / sync）
- [ ] 出图链路（gen / batch / API）
- [ ] 自检与运维（doctor / status / reset / logs）
- [ ] 补丁（`patches/`，改上游代码必须走这里）
- [ ] 文档

## 验证方式（必填）

<!-- 写清「你怎么证明它能用」，维护者会照着复现 -->

```bat
:: 我跑过的命令
pool.bat doctor
pool.bat test
python -m pytest tests/ -q
```

结果：

<!-- 贴关键输出，比如 doctor 全绿 / 出一张 1.4MB 的图 -->

## 自查清单

- [ ] 本地 `python -m pytest tests/ -q` 全过
- [ ] `python -m ruff check scripts/ tests/` 无新增告警
- [ ] `python scripts/lint_bat.py` 通过（改了 `.bat` 必查）
- [ ] `python scripts/scan_secrets.py` 通过（**没有引入任何真实卡密/密钥/内网地址**）
- [ ] 改了补丁：`python scripts/apply_patches.py --validate` 通过，且 `patches/README.md` 写清了「上游行为 → 现在行为 → 为什么」
- [ ] 新的报错都带「下一步怎么做」（而不是只抛堆栈）
- [ ] 脚本没有硬编码路径（用 `_common.Paths` / 环境变量）
- [ ] 文档与 `CHANGELOG.md` 已同步更新

## 其他说明

<!-- 截图、风险提示、破坏性变更、后续计划等 -->
