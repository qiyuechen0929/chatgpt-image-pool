# 使用须知与免责声明 / Notice & Disclaimer

> 本文件是**使用须知**（informational notice），不修改、也不附加 [LICENSE](LICENSE)（MIT）中授予的权利。
> This file is an informational notice. It does **not** modify or add conditions to the MIT license granted in [LICENSE](LICENSE).

## 1. 适用范围

本工具（ChatGPT 生图号池 / ChatGPT Image Pool Kit）用于**技术研究**，以及对
**你本人拥有、或已获得明确授权**的账号进行自动化操作。

请自行确认并遵守：

- 目标站点（如 `chatgpt.com`）的**服务条款**与使用政策；
- 你所处司法辖区的**法律法规**；
- 你所使用的指纹浏览器、代理、卡密供应商的相关协议。

## 2. 禁止用途

**不得**将本项目用于：批量滥用、绕过付费/配额限制、攻击或干扰任何服务、
欺诈、冒充他人、规避风控从事黑灰产业务，以及任何其他违法用途。

## 3. 第三方组件与资源

- 上游组件（VirtualBrowser 客户端 / 其 `api_server` / FPBrowser2API）由其各自作者提供，
  遵循其各自许可；本项目只提供脚本、补丁与文档。
- 账号、卡密、代理 IP 的获取与合法性由使用者自行负责。本项目**不提供、也不出售**任何账号或凭据。

## 4. 凭据与数据安全（请务必阅读）

为了免登录出图，本工具会把卡密中的长期 `access_token` 保存在本地 SQLite
（`data/fpbrowser.db`），并让管理后台提供本地 HTTP 接口。这意味着：

- **部署这台机器 ≈ 持有这些账号**：请按敏感机器对待，不要共享、不要暴露到公网。
- 上游后台默认凭据是 `admin/admin` 且默认监听 `0.0.0.0`，请立即修改并限制监听地址。
- 详见 [SECURITY.md](SECURITY.md)。

## 5. 免责

在适用法律允许的最大范围内：

- 作者**不对**账号封禁、风控、额度损失、数据丢失、服务中断或任何直接/间接损失承担责任；
- 作者**不保证**本项目始终可用、适用于特定目的，或与最新版本的上游组件兼容；
- 使用本项目产生的**全部后果**由使用者自行承担。

## 6. 举报与联系

发现安全问题请勿公开 issue，走 [SECURITY.md](SECURITY.md) 中的私有报告通道。
