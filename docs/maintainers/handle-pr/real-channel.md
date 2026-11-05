# 对真实渠道和服务验证

只在这些情况才需要：PR 改了流式、渠道检测、计费、协议处理等和真实上游行为有关的代码，而且单元测试用的是模拟上游。其他 PR 只跑 `scripts/verify_pr.sh` 即可。

## 开始前

- 真实上游测试会花钱，先征得维护者同意。维护者之前已同意过同类低成本测试的，可以直接做，汇报时写明花费量级。
- 只在读完整个 diff 且没发现可疑内容之后才做：下面的做法会让 PR 的代码接触真实密钥。
- 记录 `./service.sh status` 的当前状态，结束后恢复。

## 集成测试（一次性库）

需要名为 `five_api_test_*` 的一次性库和 Redis 的 15 号库。应用账号没有建库权限，用容器里的 root 建库，不要打印 root 密码，测完删掉。详见 `CONTRIBUTING.md`。

```bash
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "CREATE DATABASE five_api_test_pr CHARACTER SET utf8mb4; GRANT ALL ON five_api_test_pr.* TO \"five\"@\"%\";"'
cd /tmp/five-prN/backend   # 用 verify_pr.sh N --keep 保留 worktree
FIVE_TEST_MYSQL_DB=five_api_test_pr FIVE_TEST_REDIS_URL=redis://127.0.0.1:6379/15 \
FIVE_TEST_MYSQL_CONTAINER=five-api-mysql-1 <主仓库>/.venv/bin/pytest -q tests/integration
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "DROP DATABASE five_api_test_pr;"'
```

## 用 PR 版本的后端测真实渠道

在 worktree 里用另一个端口（5003），不要覆盖主仓库正在运行的 5002。worktree 里没有 `.env` 和 `data/secrets.json`（都被 git 忽略），在子 shell 里加载主仓库的，不要打印内容：

```bash
cd /tmp/five-prN/backend && ( set -a; . <主仓库>/.env; set +a
  export SECRETS_FILE=<主仓库>/data/secrets.json NO_PROXY=127.0.0.1,localhost
  nohup setsid <主仓库>/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5003 </dev/null >/tmp/prN.log 2>&1 &
  echo $! > /tmp/prN.pid )
```

然后：

- 只调用管理接口（例如渠道「测试」）时，不需要新建 Key。
- 要走推理接口时，新建一个额度极小、限定模型的临时 API Key，测完立即吊销。已有 Key 只存前缀，拿不到明文。
- 管理接口需要管理员登录。不要猜密码；不知道时问维护者，或者仅在本地验证时用应用自己的 `create_access_token` 签发短期 token，用完删除。
- 用 Claude Code、Codex 做端到端验证时，`~/.claude/settings.json` 里的 `env` 会覆盖 shell 环境变量，可能用到已有的 Key 而不是测试 Key；先确认日志里记在哪个 Key 名下，并把花费如实告诉维护者。
- 停进程用记下的 PID：`kill $(cat /tmp/prN.pid)`。不要用 `pkill -f`，匹配串出现在自己的命令行里会把自己的 shell 杀掉。

## 结束清理

worktree、分支（`verify_pr.sh` 不带 `--keep` 会自动清理）、一次性库、临时 Key、token 文件、5003 的进程，以及按开始前记录的状态恢复开发服务。
