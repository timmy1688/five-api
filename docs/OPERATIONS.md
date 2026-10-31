# 部署、升级与故障处理

## 开发与单机发布

日常开发使用 `./service.sh start`，Uvicorn 5002、Vite 5001；脚本只启动 MySQL、Redis 依赖容器，不启动网关容器。运行版本见 `/openapi.json`。修改依赖后重跑 `./service.sh install`。

发布使用根目录 Dockerfile 与 Compose。镜像基础层固定摘要，Python 依赖全部固定在 backend/requirements.txt，pip 与 npm 分别走阿里云 PyPI 镜像和 npmmirror，运行用户为 UID/GID 10001。

### 多进程

镜像以 `uvicorn --workers N` 启动多个进程共享同一端口，worker 退出由 Uvicorn 自动拉起。N 默认为容器可用 CPU 核数，最多 8；在 Compose gateway 的 environment 填 `WORKERS` 可改。Kubernetes 等按副本扩容的环境建议 `WORKERS: 1`，多开副本。

- 所有限额、预占与扣费都在 MySQL 行锁与 Redis 中完成，多个 worker、多个容器之间结果一致，不会多扣或超额。
- 每个 worker 在 Redis 写 `five:process:<id>` 心跳（默认 60 秒过期，`PROCESS_STALE_SECONDS`）。worker 崩溃后，其他 worker 接管它留下的预占：未发往上游的释放额度；已发往上游的标为未知结果并继续占用，等待核对，迟到的用量仍按实际金额结算。Redis 不可用时不接管。
- 结算恢复、额度重置、日志清理、模型巡检和渠道探测用 Redis `SET NX` 按周期认领，同一周期只有一个 worker 执行。
- 所有 worker 必须使用同一个 SECRET_KEY：不填时入口脚本在容器启动时随机生成一个并传给全部 worker，重启容器后仍需重新登录。
- 每个 worker 有独立的 MySQL 连接池，默认上限 `200 / WORKERS`（10–50 之间），可用 `MYSQL_POOL_SIZE` 指定。Compose 中的 MySQL 设为 `--max-connections=500`；使用外部 MySQL 时确保 `max_connections` ≥ 容器数 × WORKERS × 连接池上限再加余量。
- `/metrics` 汇总全部 worker（`PROMETHEUS_MULTIPROC_DIR`，镜像已设置）。

性能见 [压测报告](BENCHMARK.md)：模拟环境下 8 核机器每分钟约 2.6 万次；同一租户的扣费要排队，单个租户每分钟约 9000 次，不随 worker 数增加。真实 DeepSeek 渠道下网关让首字只慢约 20 毫秒以内。

留意磁盘：MySQL 默认保留 30 天 binlog，高流量下增长很快，压测中数万次请求就写出了 1GB。磁盘写满时 MySQL 和 Redis 都停止写入，请求和结算会卡住。生产环境要监控磁盘，空间紧张时可执行 `PURGE BINARY LOGS BEFORE NOW() - INTERVAL 3 DAY` 清理旧 binlog。

- `./service.sh deploy`：`docker compose up -d --build`，不需要预先生成任何配置。
- 网关对外开放 8080 端口，客户端直连时 Key 的 IP 白名单直接按真实来源 IP 判断。MySQL、Redis 端口只绑定本机。
- 网关容器无状态，可随时重建。MySQL、Redis 数据位于 `data/mysql`、`data/redis`。
- `/healthz` 检查 MySQL、Redis；镜像探针 4 秒超时。
- Compose 给网关 40 秒退出时间，Uvicorn 请求排空上限 30 秒，再处理后台收尾。未完成的账务记录由下次启动恢复。

## 网络

网关前面有反向代理或负载均衡时，只把这些受控来源写入 `FORWARDED_ALLOW_IPS`，不能使用 `*`，否则客户端可伪造来源 IP 绕过 Key 的 IP 白名单。Compose 部署时在 gateway 的 environment 里添加 `FORWARDED_ALLOW_IPS`；本机反代经发布端口到达容器的来源是 Compose 网络的网关地址（`docker network inspect five-api_default` 查看），不是 127.0.0.1。代理需关闭响应缓冲，读取超时不低于 600 秒以支持流式响应。

公共上游默认要求 HTTPS；本机、私网和内部 DNS 可使用 HTTP 接 vLLM 等服务。开发确需访问公网 HTTP 时可显式设置 `ALLOW_INSECURE_UPSTREAMS=true`。上游 URL 不接受用户名密码或查询参数，凭据填写在渠道 Key 字段。

## 密钥与旧版迁移

两种外部秘密用途独立：

| 配置 | 用途 |
| --- | --- |
| SECRET_KEY | 管理 JWT 签名 |
| ENCRYPTION_KEY | 渠道 Key、告警地址和签名秘密的加密 |
| SECRETS_FILE | 包含 jwt_secret、encryption_key 的 JSON 文件 |

本地开发未配置环境变量时，全新数据会自动生成 `data/secrets.json`。已有密文时，密钥缺失或不匹配会拒绝启动；不能删除后重新生成。

镜像设置 `SECRETS_FILE` 为空，网关容器不读写密钥文件，两个密钥都可不填，与 new-api 默认方式一致：

- 不填 SECRET_KEY：每次启动随机生成，重启或重建容器后需重新登录。
- 不填 ENCRYPTION_KEY：上游 Key 用代码内置的公开密钥加密，数据库泄露即等于上游 Key 泄露。
- 需要更高安全时，在 Compose 的 gateway environment 填入两个至少 32 位、互不相同的随机值，并与数据库分开保管。已用内置密钥保存过渠道时，先填好 ENCRYPTION_KEY，执行 `docker compose run --rm --no-deps gateway python -m app.migrate_secrets --from-default` 重新加密，再启动网关；否则启动会因无法解密而拒绝。

旧版 Compose 把密钥放在 `gateway_secrets` 卷里。升级前在旧网关运行时导出 `/var/lib/five-api/secrets.json`，把其中 jwt_secret、encryption_key 分别填入新 Compose 的 SECRET_KEY、ENCRYPTION_KEY 后再启动。

从旧版数据库 `system_settings.app_secret` 升级：

1. 停止旧网关，按下一节保留数据库与旧秘密。
2. 使用新代码执行 `aerich upgrade`，应用迁移 18–22。
3. 执行 `python -m app.migrate_secrets`；Compose 对应 `docker compose run --rm --no-deps gateway python -m app.migrate_secrets`。
4. 迁移先生成外置秘密文件，再用一个数据库事务重加密渠道、告警等密文并删除数据库旧根密钥。失败时保留文件，修复原因后重跑，不要换一套文件。
5. 启动网关，验证登录、渠道解密、两个租户、Key 创建、推理和费用。

如果秘密仅在旧文件中，本地执行 `python -m app.migrate_secrets --legacy-secret-file ../data/.secret_key`。容器中执行时需将旧文件只读挂载供迁移命令读取，新密钥取自 Compose 的 ENCRYPTION_KEY，未填则用内置密钥。不要把文件内容放进命令行参数或工单。旧管理 JWT 需重新登录。

迁移 18 不提供自动降级：旧账号到租户的映射无法可靠反推。迁移 19–22 加入账务记录、用量来源、限流、模型检测、倍率和平台自用 Key 标记。旧自定义角色进入停用租户等待人工核对，旧 roles 表不再参与授权。

## 备份和恢复

当前开发测试数据按用户授权不额外备份。下面流程用于真实商用数据；自动化恢复测试仅使用专用隔离库。

数据库和密钥文件分开保存，限制访问并在独立位置保管。配置了自有 ENCRYPTION_KEY 时，仅有数据库备份不能解密渠道 Key；使用内置密钥时数据库备份须按含上游 Key 对待。

停止网关后，在受控终端设置 `umask 077`，使用现有数据库账号执行：

```bash
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u "$MYSQL_USER" --no-tablespaces --single-transaction "$MYSQL_DATABASE"' > mysql.sql
cp .env five-api.env
```

两份文件分开加密保存。Redis 的视频任务和滚动窗口数据如需保留，应一并保留 Redis 数据目录；丢失 Redis 会丢失这些状态，不影响已提交的 SQL 账单。

恢复时保持网关停止，将 SQL 导入选定数据库，把对应的 `.env` 放回项目根目录并设为 0600，再运行匹配版本的迁移与启动。涉及不兼容 schema 时，恢复整套对应版本数据和秘密，不能只回退镜像。

验收覆盖全新 0→22 迁移、旧 17→22 升级、隔离库 mysqldump/恢复及密文解密。不会清理其他数据库。

## 结算异常

后台保留自动结算与重试，不常驻独立「结算恢复」页签。系统设置仅在存在 failed、uncertain 记录时显示异常入口。

- reserved：请求预占；调用上游前先持久化 dispatched 标记。
- pending：已保存实际用量，等待事务扣费。失败按有限退避重试。
- settled：Key、租户、日志、日汇总已一起提交；重复恢复不重复扣费。
- failed：自动重试耗尽，或定价计算异常，保留占用等待处理。
- uncertain：上游可能已执行但没有可信结果，保留估算占用。
- released：已确认可释放；不改写历史已用金额。

已知实际费用使用 retry；未知结果与上游核对后，可以记录原因释放或按保存的估算计费。对应平台接口 `/api/settlements/{id}/retry`、`/resolve`。上游执行与本地落库之间存在故障窗口，不能承诺上游调用恰好一次。

`five_settlements_waiting{state="failed"}`、`state="uncertain"` 为 Prometheus 关注指标，重试计数为 `five_settlement_retries_total`。

## 模型巡检与价格

模型广场的「巡检设置」控制全平台定时检测：可用性 15 分钟、GPT/Claude 降智参考 24 小时。启动后先等待 15 秒，后台每轮扫描到期任务；最多同时两个检测，繁忙时排队顺延。最近结果持久化，重启不会立即重复整轮。停用渠道、非文本模型不参与；没有 GPT/Claude 渠道时不产生降智检测记录。

健康检测会调用实际文本推理端点。降智参考用三类合成任务验证输出，不用于鉴定型号或自动停用渠道。检测产生平台上游费用，不扣客户额度；记录位于 model_probes，默认没有租户访问权限。

客户价 = 模型售价 × 渠道价格倍率；渠道为某模型设了固定价时直接用固定价。请求开始时按候选渠道各自快照报价，按最贵的候选预占，按实际服务渠道结算；导入参考价不覆盖已有配置。

迁移 24 把模型售价的倍率乘进单价后删除倍率列，客户价不变；删除渠道上游成本表、成本倍率、分时规则和日志、日汇总的 upstream_cost。所有渠道倍率为 1、所有 Key 不绑定渠道，行为与升级前一致。降级只恢复列结构，渠道倍率、固定价和 Key 渠道绑定会丢失，上游成本不可恢复。

## 泄露和故障排查

推理 Key 泄露：立即撤销，创建新 Key，更新受控应用配置；新建不恢复已用额度。账号凭据泄露：重置密码撤销旧 JWT。上游 Key 泄露：在厂商侧撤销并更新渠道；外置秘密泄露需要人工安排重新加密与会话失效，没有自动轮换服务。

按响应 X-Request-ID 查日志。客户端提供的 ID 单独记录，不用作结算幂等键。日志区分 upstream、estimated、mixed、legacy 用量来源。缺失报价、认证依赖、额度校验故障均不默认放行。
