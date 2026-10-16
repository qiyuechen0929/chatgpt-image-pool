# 安全策略 / Security Policy

## 支持范围

| 版本 | 是否维护 |
|---|---|
| 1.1.x（最新） | ✅ |
| 1.0.x | ⚠️ 仅严重问题 |
| < 1.0 | ❌ |

## 报告安全问题

**请勿用公开 issue 报告安全问题。** 优先用 GitHub 私有报告通道：

👉 https://github.com/qiyuechen0929/chatgpt-image-pool/security/advisories/new

如果无法使用，可以开一个**不含细节**的 issue，写「我有安全问题要报告，请给我联系方式」，
维护者会回你一个私下渠道。

请在报告里包含：

- 问题类型（凭据泄露 / 任意代码执行 / 越权 / 依赖漏洞 / 逻辑缺陷 …）
- 影响版本与最小复现步骤
- 你在本地的验证结果
- 你建议的修复方向（可选）

我们会在 **7 天内**给出初步响应，并在修复后于 `CHANGELOG.md` 与 advisory 里致谢（如果你愿意具名）。

## 本项目的安全边界（重要）

这个工具是「**在你的机器上自动化你自己的浏览器与账号**」，因此：

1. **长期保存 access_token**：为了免登录出图，窗口池会把卡密里的长 token 存进本地
   SQLite（`data/fpbrowser.db`）。这意味着 **部署这台机器 = 持有这些账号**。
   请按敏感机器对待（不要共享、不要暴露到公网）。
2. **管理后台默认凭据**：上游 FPBrowser2API 默认 `admin/admin`，且默认监听 `0.0.0.0`。
   如果你的机器能被局域网访问，请务必改密码，并把 `server.host` 改成 `127.0.0.1`。
3. **公开 API Key**：`/v1/*` 用 `api_key` 鉴权（存在 `system_config`）。任何人拿到它
   就能消耗你的账号额度，请勿写进前端/公开仓库。
4. **插件长连接**：扩展通过 `ws://<base_url>/api/extension/ws` 连回后端，`bridge_token` 是
   唯一鉴权手段。跨机部署时请只在可信内网开放该端口，并设置足够随机的 token
   （`pool.bat setup` 会自动生成）。
5. **补丁会改上游代码**：`patches/` 是必须的改造，但请知悉它修改了 VirtualBrowser 的
   `api_server`。升级上游后要重新打补丁并用 `pool.bat doctor` 复核。

## 我们主动做的防护

- 仓库内**不含任何真实凭据**：`scripts/scan_secrets.py` 会扫描卡密、JWT、密钥、内网地址，
  CI 每次提交都跑；测试夹具里的样本用 `# scan-secrets:allow` 显式豁免。
- `.gitignore` 默认屏蔽 `accounts*.txt`、`*.db`、`logs/`、`.env`、`output/`。
- 补丁自检（`pool.bat patch --validate`）会拦截「补丁里夹带密钥」。
- 所有脚本**不打印完整 token**（只显示有无与到期时间）、不打印密码。

## 依赖安全

```bash
# 上游依赖由 requirements.txt 固定（FPBrowser2API）
python -m pip list --outdated

# 检查已知漏洞（可选）
pip install pip-audit && pip-audit -r requirements.txt
```

## 合规提醒

本工具只应用于**你拥有或已获授权**的账号，并遵守目标站点的服务条款与当地法律。
不提供、也不接受任何用于滥用、绕过付费、攻击或黑产的贡献。
