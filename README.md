# Five API

[English](docs/README.en.md) · [开发计划](docs/DEVELOPMENT_PLAN.md) · [运维与升级](docs/OPERATIONS.md) · [兼容矩阵](docs/COMPATIBILITY.md)

[![CI](https://github.com/timmy1688/five-api/actions/workflows/ci.yml/badge.svg)](https://github.com/timmy1688/five-api/actions/workflows/ci.yml)

轻量多租户 AI 网关，提供 OpenAI、Anthropic 原生协议与 Vue 管理后台。采用 MIT 许可证，可用于商业部署。当前开发版本为 **0.4.0**，发布状态见 [CHANGELOG](CHANGELOG.md)。

## 产品范围

- **两种固定身份**：平台管理员、租户。平台负责开户、总额度、模型授权和限流；一个租户一个账号，租户自行管理 Key，不创建子账号。
- **平台自用 Key**：首页和 API Key 页面均可创建，自动归入平台内部额度空间。管理员不代租户创建客户 Key。
- **可靠计费**：多个 Key 共享租户累计美元额度，并受各自上限约束。足额预占、报价快照、MySQL 事务结算、幂等恢复；结果不确定时保留占用供核对。
- **租户限流**：共享 RPM、TPM 与并发限制，创建新 Key 不能绕过。新租户默认 120 RPM、100,000 TPM、10 并发，均可由平台调整。
- **模型广场**：展示实际计费价、渠道、健康结果和巡检时间。可用性默认每 15 分钟检测；GPT、Claude 的降智参考检测默认每天一次，也可立即检测。
- **售价与成本分开**：客户计费倍率与渠道折扣独立设置。导入参考价格只补缺失项，保留已有价格、倍率及启停状态。
- **路由与协议**：保留渠道优先级、号池、故障转移、粘性会话、缓存计量、模型回退及现有多模态端点。
- **最小运营界面**：账号管理合并租户账号与平台管理员；设置按配置、路由、告警、监控分组。取消 CSV 账单对账和独立结算恢复页签，异常才显示核对入口。

首期不提供在线支付、组织成员层级、动态 RBAC、SSO 或多副本调度。[权限边界与管理 API](docs/MANAGEMENT_API.md) 说明账号、JWT 与推理 Key 的区别。

## 本地开发

需要 Python 3.12、Node.js 20.19+（CI 使用 24）、Docker 中的 MySQL 8 和 Redis 7：

```bash
./service.sh install
./service.sh start
```

前端：`http://127.0.0.1:5001`；后端：`http://127.0.0.1:5002`。开发使用本地 Uvicorn 和 Vite，只有数据库和 Redis 使用容器。依赖下载默认使用阿里云与 npmmirror。

首次全新安装默认账号 `admin / admin123`，首次登录必须改密。已有环境修改 `INIT_ADMIN_PASSWORD` 不会重置既有账号密码。

## 单机部署

```bash
docker compose up -d --build
```

单镜像提供后台与 API，默认只在本机 `http://127.0.0.1:8080` 监听。商用外部入口使用现有 Nginx 终止 HTTPS，参考 [Nginx 配置](deploy/nginx.conf) 和 [运维文档](docs/OPERATIONS.md)。配置正式数据库密码、初始管理员密码，并保管独立密钥文件。

渠道凭据加密主密钥与 JWT 签名密钥分离，保存在外置文件或独立环境变量中，数据库不保存主密钥。**从旧版本升级必须按运维文档完成迁移**，不能直接换回旧镜像。

## 开通与接入

1. 平台配置渠道、模型售价、客户账号、总额度和共享限流。
2. 租户首次登录修改临时密码，自行创建应用 Key，明文只显示一次。
3. 应用使用推理 Key，自动化管理使用账号登录取得的短期 JWT。

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-gateway-key",
    base_url="https://ai.example.com/v1",
)
result = client.chat.completions.create(
    model="your-configured-model",
    max_tokens=128,
    messages=[{"role": "user", "content": "Hello"}],
)
print(result.choices[0].message.content)
```

Anthropic SDK 的 `base_url` 使用网关根地址。具体端点、流式、工具与 SDK 实测版本见 [兼容矩阵](docs/COMPATIBILITY.md)。

计费价 = 基础单价 × 计费倍率；上游成本 = 渠道基础单价 × 渠道成本倍率。输入、缓存读、缓存写、输出分别计量，按次费用另计。报价缺失的未知模型不会静默免费放行；显式 0 为有效免费价格。内置目录是版本化参考数据，不是实时厂商报价。

降智参考检测通过合成题检查指令遵循、推理和工具调用，记录结果供比较，无法证明上游真实型号。定时检测会产生平台上游费用，不扣租户额度；开关与周期位于模型广场的「巡检设置」。

## 验证与贡献

```bash
cd backend
../.venv/bin/pytest -q
../.venv/bin/python -m scripts.smoke_tenants --ui
../.venv/bin/python scripts/release_check.py
```

真实 MySQL/Redis 测试、依赖更新、性能基准和浏览器准备见 [贡献指南](CONTRIBUTING.md)。安全问题请按 [安全报告流程](SECURITY.md) 处理。

网关的估算、上游计量和厂商账单可能存在差异；并发在途请求及未知结果不承诺绝对零超额。仅支持当前单进程部署方式。未验证的客户端和生产域名部署状态会在兼容、运维文档中明确列出。
