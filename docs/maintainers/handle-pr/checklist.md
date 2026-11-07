# five-api 审查清单

依据：`CLAUDE.md`（「必须保持的边界」「请求与结算」）、`CONTRIBUTING.md`、`docs/DESIGN.md`。PR 涉及相应区域时重新读一遍原文，这里只是快速索引。

## 供应链与执行（最先检查）

- [ ] `.github/workflows/*`：PR 触发的任务权限不超过 `contents: read`；没有 `pull_request_target`；PR 代码拿不到 secrets；只有 `v*` tag 的发布任务才允许 `push: true`。
- [ ] `Dockerfile`：基础镜像保留 `@sha256:` 摘要、`USER 10001:10001`、阿里云镜像源（`release_check` 会断言）。
- [ ] `backend/requirements.txt`：只有这一个文件，每行用 `==` 固定版本；新增依赖有理由并通过 `pip-audit`。
- [ ] `scripts/`、`conftest.py`、`service.sh`：不会删除 `five_api_test_*` 之外的数据，不访问外部主机，不读取 `data/secrets.json` 或 `.env`。
- [ ] 前端 `package.json` 和锁文件的改动是有意的，且两者一致。

## 计费与结算

- [ ] 事务锁顺序保持 Tenant → APIKey → Settlement。Key 扣费、租户扣费、请求日志、`usage_daily` 在同一事务提交。
- [ ] 调用前足额预占；调用上游前先持久化 `dispatched`；上游已完成的调用不会因结算失败而重放；结果未知时继续占用额度。
- [ ] 显式 0 用量与缺失用量分开记录；估算的用量标明 `usage_source`。
- [ ] 价格来自冻结的 `selling_quote` 快照；渠道 `price_overrides` / `price_multiplier` 规则不变；`ModelPrice` 停用时仍然拒绝。
- [ ] 结算状态保持：reserved、pending、failed、uncertain、settled、released。

## 流式与代理

- [ ] 渠道故障切换只发生在首包之前。
- [ ] 清理逻辑保留 `anyio` 的 shield（`move_on_after(..., shield=True)`），并正确处理取消。
- [ ] 结束事件仍算成功：`[DONE]`、`message_stop`、`response.completed`、`response.incomplete`；收到结束事件后客户端断开不记为 499。
- [ ] HTTP 200 的流里夹带错误、或流在没有结束事件时就关闭，不记为成功，也不清零渠道失败计数。
- [ ] OpenAI 接口只路由到 OpenAI 协议渠道，Anthropic `/v1/messages` 只路由到 Anthropic 协议渠道，不做跨协议转换。

## 安全与租户隔离

- [ ] 只有 `platform_admin`、`tenant` 两种固定角色，没有动态 RBAC。每个查询都带租户范围，包括历史用量、下载和删除。
- [ ] 管理 JWT 与推理 Key 用途分离；JWT 固定 `aud`、短期有效，改密递增 `token_version`。
- [ ] API Key 明文只展示一次；上游 Key 加密存储；日志、错误信息、测试夹具里没有密钥（见 `redaction`）。
- [ ] `content_filter` 只标记不拦截；`ai_audit` 是手动、事后复核。文档或代码里不接受“实时拦截”的说法。
- [ ] 新增的错误文本不泄露上游凭证和内部地址。

## 数据与迁移

- [ ] 模型有改动时，迁移由 Aerich 生成；检查生成的 MySQL SQL；不修改历史迁移。
- [ ] 全新安装和旧版升级都能跑通。

## 测试与文档

- [ ] 新行为有测试；修 bug 有回归测试，且去掉修复后会失败。
- [ ] 测试数量和 `main` 基线对比；跳过的用例要说明原因（没有 `FIVE_TEST_*` 时集成测试会跳过）。
- [ ] 用户可见的变化或迁移，在 `CHANGELOG.md` 的 `[Unreleased]` 下有条目。
- [ ] 文档与代码一致：`docs/CLIENTS.md`、`docs/DESIGN.md`、README 的说法。没有数据支撑的“优于某某”类对比不接受；保留免责声明。
- [ ] 前端：文案同时加在 `i18n/messages.ts` 的 `en` 和 `zh` 里（`zh` 的类型由 `en` 的键约束，漏写会在 `npm run build` 时报错）；菜单只改 `config/navigation.ts`；新增组件后重新生成 `components.d.ts`。

## 接口新增状态值或字段时

- [ ] 后端 schema 的 `Literal`、前端 TypeScript 类型、界面标签和颜色、汇总统计（分母、计数）、`docs/DESIGN.md` 里的接口说明同时更新，没有遗漏的一处。
- [ ] 旧前端遇到新状态值不会崩溃（向后兼容），顶层汇总字段（如 `success`）的新含义写进文档。
- [ ] 新增的「跳过 / 可选」语义只对明确列出的情况生效（例如固定的 HTTP 状态码和协议），其他错误仍然算失败，且有对应的反向测试。

## 常见的非阻塞问题（作为后续 PR 建议）

- 上游本来就没有的端点被当成失败展示（例如 DeepSeek 的 Anthropic 端点没有 `/v1/models`）。
- 命名、少量重复代码、缺少边界用例的测试、文档措辞。
