# Five API 开发指南

FastAPI、Tortoise ORM、MySQL 8、Redis 7；Vue 3、Element Plus。开发使用本地 Uvicorn :5002、Vite :5001，只有 MySQL/Redis 为容器。不要把日常开发切换为网关容器。

产品范围、批次与验收见 [开发计划](docs/DEVELOPMENT_PLAN.md)，授权见 [权限设计](docs/PERMISSIONS_DESIGN.md)，操作见 [运维文档](docs/OPERATIONS.md)。

## 常用命令

- `./service.sh install`：Python 3.12 开发锁与 npm ci，默认国内源。
- `./service.sh start`：应用迁移，重新启动两个本地开发进程，保留数据库依赖。
- `cd backend && ../.venv/bin/pytest -q`：快测；真实服务使用显式隔离库环境变量。
- `cd backend && ../.venv/bin/python -m scripts.smoke_tenants --ui`：真实 HTTP/浏览器，清理自己创建的数据。
- `cd frontend && npm run build`：类型与生产构建。
- `cd backend && ../.venv/bin/aerich migrate --name description`：生成后检查 MySQL SQL。
- `python backend/scripts/release_check.py`：版本、依赖锁和发布文件检查。

用户已授权当前测试环境的迁移、清理与开发操作，不需额外备份测试数据。商用恢复流程仍需完整保留对应数据库与外置秘密。

## 必须保持的边界

- platform_admin、tenant 两种固定角色，没有动态 RBAC。租户只能管理自己的 Key，不能建账号或改归属。
- 管理员可创建平台自用 Key，自动归内部 is_system 空间；不代客户创建 Key。账号与归属不可变。
- 管理 JWT 与推理 Key 用途分离。JWT 固定 aud、短期有效，改密递增 token_version。
- 所有开放接口都在服务端校验租户范围，含历史用量、视频查询、下载和删除。
- APIKey 明文只展示一次，永久撤销保留已用；Key 新建不能恢复租户额度。
- 主密钥位于 data/secrets.json 或独立环境变量，与 JWT 密钥不同，数据库不存根密钥。网关容器不读写密钥文件：未配置时 JWT 每次启动随机、上游 Key 用内置公开密钥加密（同 new-api 默认安全级别），改用自有密钥用 migrate_secrets --from-default。旧版升级使用 app.migrate_secrets。

## 请求与结算

内部 UUID → Key/租户状态、模型、IP、RPM → 候选路由 → selling_quote 快照 → 两层 TPM、SQL 足额预占、两层并发 → 持久化 dispatched → 上游 → 持久化用量 → SQL 事务结算 → 后台恢复。

事务锁顺序统一为 Tenant → APIKey → Settlement。Key、租户扣费、请求日志和 usage_daily 必须同时提交。结算失败不能让已完成的上游调用重放；未知结果继续占用供核对。滚动限额的 Redis team 前缀保留用于继承旧数据。

客户价按实际服务渠道计算：渠道 price_overrides 有该模型时用固定价，否则 ModelPrice（或参考目录）× 渠道 price_multiplier；ModelPrice 停用时即使有固定价也拒绝。Key channel_ids 非空时只在其中选路和故障切换，按候选中最贵的报价预占。不记录上游成本。报价缺失不静默记 0，显式零价有效。缓存读、缓存写、输入、输出分别计量；Anthropic input_tokens 不含缓存，要先补齐为 OpenAI prompt_tokens 口径。

流式仅首包前切换；清理须保留 anyio shield，正确处理取消。显式 0 用量与缺失用量分开记录，缺失字段估算并标明 usage_source。

## 模型巡检与界面

model_checks 为合成检查，model_monitor 为单进程定时循环，ModelProbe 持久化结果。默认健康 900 秒、GPT/Claude 降智参考 86400 秒，Redis 锁与全局两个并发租约避免重复。不能把模型自报名称或小题分数当成型号证明，也不因能力题失败自动停用渠道。

菜单统一在 frontend/src/config/navigation.ts。账号管理包含租户账号、平台管理员。设置分配置、路由、告警、监控四组；结算仅在失败/未知异常时显示处理入口。CSV 账单对账已移除。

## 变更约定

Python 依赖只有 backend/requirements.txt 一个文件，全部 == 固定版本并审计；Docker 与本地安装均走阿里云源。记录用户可见变化、迁移和兼容边界，更新 CHANGELOG 与计划；发布标签需匹配 0.4.0 等实际版本。测试不得清理其他数据库或 Redis 全库，不记录秘密。详情见 CONTRIBUTING.md。
