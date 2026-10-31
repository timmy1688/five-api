# 路线图

Five API 的方向是：**给客户转售 AI 接口、需要按客户精确分账的团队用的自托管网关**。计费正确优先于功能数量，任何新功能都不能削弱「先预占再放行、扣费和日志同事务提交」这两条底线。

想法和问题欢迎到 [Discussions](https://github.com/timmy1688/five-api/discussions) 讨论，确定要做的会转成 Issue。

## 发版节奏

- 每月一个小版本（0.5、0.6……），在 [更新记录](CHANGELOG.md) 写明用户可见变化、迁移和升级步骤。
- 安全和计费问题随时发补丁版本（如 0.4.1）。
- 打 `v*` 标签后 CI 自动构建 amd64/arm64 镜像推送到 `ghcr.io/timmy1688/five-api`，并生成 GitHub Release。
- 1.0 之前可能有不兼容的改动，都会在更新记录里给出迁移方式。

## 近期（0.5）

- **客户端**：在公网 HTTPS 部署上实测 Cursor；Claude Code、Codex 新版本回归，结果更新到 [接入教程](docs/CLIENTS.md)。
- **国内部署**：发布镜像同步到国内镜像仓库，解决 ghcr.io 拉取慢的问题。
- **多台机器部署**：验证并写清楚多台网关共用 MySQL、Redis 的部署方式（目前已验证的是单机多进程）。

## 之后

- 管理后台 OIDC 单点登录。
- 更多上游厂商的实测记录，和对应的计费口径说明。

## 不做

- 在线支付、自助注册、兑换码：这是公开中转站的需求，new-api 做得更好。
- 自定义角色和动态权限：固定的平台管理员和租户两种角色，是计费边界清晰的前提。
- 协议互转（OpenAI 请求转 Anthropic 渠道等）：互转后用量口径难以保证，所以只做原生透传。

## 适合新贡献者的任务

带 [good first issue](https://github.com/timmy1688/five-api/labels/good%20first%20issue) 标签的 Issue 是改动小、边界清楚的任务。目前适合认领的方向：

- 实测一个新客户端（Cline、Continue、Cherry Studio 等），按 [接入教程](docs/CLIENTS.md) 的格式补充配置和实测版本。
- 把 [运维文档](docs/OPERATIONS.md) 或 [设计文档](docs/DESIGN.md) 翻译成英文。
- 用自己的渠道跑一遍 `scripts.real_benchmark`，把结果补充到 [压测报告](docs/BENCHMARK.md)。
- 给错误信息、界面文案提改进。

开发环境和测试方法见 [贡献指南](CONTRIBUTING.md)。
