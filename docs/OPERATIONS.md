# 部署、升级与故障处理

## 开发与单机发布

日常开发使用 `./service.sh start`，Uvicorn 5002、Vite 5001；脚本只启动 MySQL、Redis 依赖容器，不启动网关容器。运行版本见 `/openapi.json`。修改依赖后重跑 `./service.sh install`。

发布使用根目录 Dockerfile 与 Compose。镜像基础层固定摘要，Python 运行依赖与前端依赖有锁文件，运行用户为 UID/GID 10001。只运行一个 Uvicorn worker；当前恢复与定时巡检逻辑未设计为多副本调度。

- `docker compose up -d --build`：网关只绑定宿主机 127.0.0.1:8080。
- MySQL、Redis 数据位于 `data/mysql`、`data/redis`。
- 独立密钥文件位于 `gateway_secrets` 卷的 `/var/lib/five-api/secrets.json`，权限 0600，属主 10001。
- `/healthz` 检查 MySQL、Redis；镜像探针 4 秒超时。
- Compose 给网关 40 秒退出时间，Uvicorn 请求排空上限 30 秒，再处理后台收尾。未完成的账务记录由下次启动恢复。

不要使用 `docker compose down -v` 作为日常更新命令，它会移除密钥卷。

## Nginx 与 HTTPS

使用现有 Nginx，参考 [nginx.conf](../deploy/nginx.conf)。替换域名和证书路径，执行 `nginx -t` 后重新加载。关闭代理缓冲，保留 600 秒上游读取超时以支持流式响应。示例不负责签发证书。

只信任受控代理 IP，不能使用 `FORWARDED_ALLOW_IPS=*`。当宿主机 Nginx 通过 Docker 映射端口连接网关时，网关通常看到 Docker 网桥网关 IP；使用 `docker network inspect five-api_default` 核对来源，将该受控 IP 写入 Compose 的 `FORWARDED_ALLOW_IPS` 后重建网关。HTTP 端口必须继续只绑定本机，Nginx 覆盖客户端传来的转发头。

本次验收包含本地证书可信/不可信场景和受信代理边界；没有在公网域名申请或部署证书。

公共上游默认要求 HTTPS；本机、私网和内部 DNS 可使用 HTTP 接 vLLM 等服务。开发确需访问公网 HTTP 时可显式设置 `ALLOW_INSECURE_UPSTREAMS=true`。上游 URL 不接受用户名密码或查询参数，凭据填写在渠道 Key 字段。

## 密钥与旧版迁移

两种外部秘密用途独立：

| 配置 | 用途 |
| --- | --- |
| SECRET_KEY | 管理 JWT 签名 |
| ENCRYPTION_KEY | 渠道 Key、告警地址和签名秘密的加密 |
| SECRETS_FILE | 包含 jwt_secret、encryption_key 的 JSON 文件 |

全新数据没有密文时，未配置的密钥可以自动生成外置文件。本地默认 `data/secrets.json`；如果使用环境变量，应配置两个互不相同的至少 32 字符随机值。已有密文时，文件缺失或主密钥不匹配会拒绝启动；不能删除文件重新生成。

从旧版数据库 `system_settings.app_secret` 升级：

1. 停止旧网关，按下一节保留数据库与旧秘密。
2. 使用新代码执行 `aerich upgrade`，应用迁移 18–22。
3. 执行 `python -m app.migrate_secrets`；Compose 对应 `docker compose run --rm --no-deps gateway python -m app.migrate_secrets`。
4. 迁移先生成外置秘密文件，再用一个数据库事务重加密渠道、告警等密文并删除数据库旧根密钥。失败时保留文件，修复原因后重跑，不要换一套文件。
5. 启动网关，验证登录、渠道解密、两个租户、Key 创建、推理和费用。

如果秘密仅在旧文件中，本地执行 `python -m app.migrate_secrets --legacy-secret-file ../data/.secret_key`。容器需将文件只读挂载供迁移命令读取；确保输出密钥文件最后归属 UID 10001。不要把文件内容放进命令行参数或工单。旧管理 JWT 需重新登录。

迁移 18 不提供自动降级：旧账号到租户的映射无法可靠反推。迁移 19–22 加入账务记录、用量来源、限流、模型检测、倍率和平台自用 Key 标记。旧自定义角色进入停用租户等待人工核对，旧 roles 表不再参与授权。

## 备份和恢复

当前开发测试数据按用户授权不额外备份。下面流程用于真实商用数据；自动化恢复测试仅使用专用隔离库。

数据库和密钥文件分开保存，限制访问并在独立位置保管。仅有数据库备份不能解密渠道 Key。

停止网关后，在受控终端设置 `umask 077`，使用现有数据库账号执行：

```bash
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u "$MYSQL_USER" --no-tablespaces --single-transaction "$MYSQL_DATABASE"' > mysql.sql
docker compose exec -T gateway cat /var/lib/five-api/secrets.json > secrets.json
```

如果网关已停止，使用维护容器读取密钥卷，或者在停机前导出密钥文件。两份文件分开加密保存。Redis 的视频任务和滚动窗口数据如需保留，应一并保留 Redis 数据目录；丢失 Redis 会丢失这些状态，不影响已提交的 SQL 账单。

恢复时保持网关停止，将 SQL 导入选定数据库，恢复对应外置密钥文件并校正 0600/UID 10001 权限，再运行匹配版本的迁移与启动。涉及不兼容 schema 时，恢复整套对应版本数据和秘密，不能只回退镜像。

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

客户售价与渠道成本独立。倍率和单价在请求开始时快照；导入参考价不覆盖已有配置。旧历史 upstream_cost 回填原 cost，仅供解释旧数据，不代表已经取得厂商真实结算成本。

## 泄露和故障排查

推理 Key 泄露：立即撤销，创建新 Key，更新受控应用配置；新建不恢复已用额度。账号凭据泄露：重置密码撤销旧 JWT。上游 Key 泄露：在厂商侧撤销并更新渠道；外置秘密泄露需要人工安排重新加密与会话失效，没有自动轮换服务。

按响应 X-Request-ID 查日志。客户端提供的 ID 单独记录，不用作结算幂等键。日志区分 upstream、estimated、mixed、legacy 用量来源。缺失报价、认证依赖、额度校验故障均不默认放行。
