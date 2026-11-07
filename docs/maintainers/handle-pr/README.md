# 处理 PR（five-api）

维护者处理外部 Pull Request 的流程：分诊、审查、本地验证、合并和发版。人可以直接按它操作；AI 编程助手（Cursor、Claude Code、Codex 等）也可以照着执行，入口见文末。

给 AI 助手的约定：回复使用中文。先给结论，再给理由，最后给可直接照做的步骤（命令，或网页上点哪里）。默认假设没有 GitHub token，也没有 `gh` 命令行：合并、评论、关闭由维护者在网页上操作，助手负责把判断、验证和评论文字准备好。

## 流程

复制并逐项勾选：

```
- [ ] 1 获取 PR 信息并分诊（scripts/pr_info.py）
- [ ] 2 按风险读完整个 diff（checklist.md）
- [ ] 3 验证（scripts/verify_pr.sh；必要时按「真实渠道验证」）
- [ ] 4 给结论、合并顺序和回滚方案
- [ ] 5 起草评论（templates.md）
- [ ] 6 合并后：拉取、CI、测试、清理、CHANGELOG、发版
```

## 文件

| 文件 | 用途 |
| --- | --- |
| `scripts/pr_info.py` | 一条命令列出未合并 PR，或汇总某个 PR：大小、是否最新、CI、改动文件、风险区、模板是否填写 |
| `scripts/verify_pr.sh` | 在独立 worktree 里跑快测、发版检查、前端构建，并自动清理 |
| `checklist.md` | 本仓库的风险清单 |
| `templates.md` | 评论模板和给维护者的合并步骤 |

## 1. 获取与分诊

```bash
python docs/maintainers/handle-pr/scripts/pr_info.py        # 列出未合并的 PR
python docs/maintainers/handle-pr/scripts/pr_info.py N      # 汇总 PR #N
git fetch origin pull/N/head:pr-N                           # 取代码
```

有 `gh` 时也可以用 `gh pr view N`、`gh pr diff N`。脚本只用公开 API，默认通道失败时自动改为不走代理再试一次。

读代码之前，根据汇总先判断：

- 是否符合 `docs/DESIGN.md` 的范围，是否落在 `docs/ROADMAP.md`「不做」一节里？一个 PR 只做一件事。
- 改动体量。无关文件很多时，请作者拆分。
- 是否与其他未合并 PR 改了同一批文件。最常见的冲突是 `CHANGELOG.md`。
- PR 模板（改了什么 / 验证 / 升级）是否有实质内容；作者自己写明「没做」的验证，要在自己的验证里补上。
- CI 状态。CI 的 `image` 任务是 `push: false`，只有 `v*` tag 才会发布镜像。第一次提交的 fork PR 可能没有 CI 记录，需要维护者在网页上批准运行。
- 是否基于最新的 `main`。不是的话，合并前要作者或维护者点「Update branch」。
- 是否是对之前评论或 issue 的跟进。是的话，找出当时提的问题，最后核对这个 PR 是否真的解决了它，并在真实环境里确认问题消失。

网络问题：

- 网络命令逐条执行并加超时（`timeout 60 ...`）。多条命令串在一起卡住时，看不出是哪一步出了问题。
- SSH 连不上 GitHub 时，公开仓库可以改用 HTTPS：`git fetch https://github.com/timmy1688/five-api.git main`。
- 用 `head_sha` 过滤 Actions 运行记录时，要用完整的 40 位 SHA，短 SHA 有时查不到。

## 2. 读 diff

结论之前必须读完每一个改动文件，并按 [checklist.md](checklist.md) 的风险区逐项检查。先看 `.github/`、`Dockerfile`、`requirements.txt`、`scripts/`、`conftest.py`，这些会在维护者机器或 CI 上执行，先读再跑。

- 先读测试，再读实现。测试里的用例边界就是作者认为的行为；然后自己找测试没覆盖的边界，例如其他状态码、超时、响应体格式错误、只有一项结果的情况。
- 对让你犹豫的地方（变量有没有初始化、响应模型的字段允许不允许 `None`），用 `git show pr-N:路径` 读完整上下文再下结论，不要凭 diff 片段猜。

## 3. 验证

不要在主工作区测试，也不要连开发库。读完 diff 之后再执行：

```bash
docs/maintainers/handle-pr/scripts/verify_pr.sh N
```

它会取 PR 的代码到 `/tmp/five-prN`，跑快测、发版检查，改了前端就跑构建（含类型检查），最后删除 worktree 和本地分支（想保留用 `--keep`）。

看结果时：

- 快测数量和 `main` 上的基线对比，新增数量要和 PR 新增的用例对得上（参数化用例按组合数算），跳过数应不变。基线要在干净的 worktree 里取：主工作区如果构建过前端（`backend/static` 存在），会多一条 `GET /{full_path:path}` 的路由守卫用例，数量对不上时先排除这个因素。可以用 `pytest --collect-only -q` 在两边各收集一次再 `diff`。
- 脚本提示模型或迁移有改动时，另外用一次性库测全新安装和旧版升级。
- 有多个 PR：按计划的合并顺序，在临时分支上合在一起测，在那里解决冲突，让维护者提前知道会发生什么。
- PR 改了流式、渠道检测、计费等依赖真实上游的行为时，按下面的「真实渠道验证」再验证一次，并如实写出哪些路径没法在真实上游复现。

### 真实渠道验证

只在 PR 改了和真实上游行为有关的代码、且单元测试用的是模拟上游时才做。真实上游测试会花钱，先征得维护者同意（之前同意过同类低成本测试的可以直接做，汇报时写明花费量级）；只在读完整个 diff 且没发现可疑内容后做，因为这会让 PR 的代码接触真实密钥。开始前记录 `./service.sh status`，结束后恢复。

集成测试用一次性库 `five_api_test_*` 和 Redis 15 号库。应用账号没有建库权限，用容器里的 root 建库，不要打印 root 密码，测完删掉：

```bash
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "CREATE DATABASE five_api_test_pr CHARACTER SET utf8mb4; GRANT ALL ON five_api_test_pr.* TO \"five\"@\"%\";"'
cd /tmp/five-prN/backend   # 用 verify_pr.sh N --keep 保留 worktree
FIVE_TEST_MYSQL_DB=five_api_test_pr FIVE_TEST_REDIS_URL=redis://127.0.0.1:6379/15 \
FIVE_TEST_MYSQL_CONTAINER=five-api-mysql-1 <主仓库>/.venv/bin/pytest -q tests/integration
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "DROP DATABASE five_api_test_pr;"'
```

用 PR 版本的后端测真实渠道时，在 worktree 里用 5003 端口，不要覆盖主仓库的 5002。worktree 里没有 `.env` 和 `data/secrets.json`，在子 shell 里加载主仓库的，不要打印内容：

```bash
cd /tmp/five-prN/backend && ( set -a; . <主仓库>/.env; set +a
  export SECRETS_FILE=<主仓库>/data/secrets.json NO_PROXY=127.0.0.1,localhost
  nohup setsid <主仓库>/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5003 </dev/null >/tmp/prN.log 2>&1 &
  echo $! > /tmp/prN.pid )
```

- 只调用管理接口（例如渠道「测试」）时，不需要新建 Key。要走推理接口时，新建额度极小、限定模型的临时 Key，测完立即吊销；已有 Key 只存前缀，拿不到明文。
- 管理接口需要管理员登录。不要猜密码；不知道时问维护者，或仅在本地用应用自己的 `create_access_token` 签发短期 token，用完删除。
- 用 Claude Code、Codex 端到端验证时，`~/.claude/settings.json` 里的 `env` 会覆盖 shell 环境变量，可能用到已有的 Key；先确认日志记在哪个 Key 名下，并如实告诉维护者花费。
- 停进程用记下的 PID：`kill $(cat /tmp/prN.pid)`。不要用 `pkill -f`，匹配串出现在自己的命令行里会把自己的 shell 杀掉。
- 结束后清理 worktree、分支、一次性库、临时 Key、token 文件和 5003 的进程。

## 4. 结论

按这个格式汇报：

```
结论：可以合并 / 修改后合并 / 不建议合并
理由：2-4 条，每条指向文件或测试
已验证：命令和结果（数量要真实）
未验证：哪些路径只靠单元测试，哪些没法在真实上游复现
合并顺序：先 X 后 Y，原因
回滚：出问题如何撤销
```

规则：

- 如实写出没验证的部分，不要声称覆盖了没跑过的真实上游。
- 区分「必须改」和「建议改」。建议项作为后续 PR 提出，不当作合并条件。
- 合并顺序：风险低、作为基础的 PR 先合；改同一热点文件的 PR 排后面。第一个合并后，第二个要点「Update branch」并处理 CHANGELOG 冲突。
- 未经作者同意，不要往贡献者的分支推提交。需要小改动时，在评论里建议，或者先合并再在 `main` 上修，并保留对作者的致谢。
- 回滚：在已合并的 PR 页面点 Revert 会生成回滚 PR；本地用 `git revert -m 1 <合并提交>`。已通过 tag 发布的镜像无法撤回，所以打 tag 之前要验证清楚。

合并由维护者在网页上操作，给出具体步骤：打开 PR 页面，拉到最下面的框，确认显示 "No conflicts with base branch" 且检查项都是绿色，点绿色的 Merge pull request，选 Create a merge commit（保留贡献者的提交历史），再点 Confirm merge。页面提示分支落后时，先点 Update branch 并等 CI 重新跑完。维护者找不到按钮时，请他发截图。

## 5. 评论

用 [templates.md](templates.md)。写具体：验证了什么、没能验证什么，后续建议标明是可选的。

## 6. 合并后

维护者说「合并了」之后，先用 `pr_info.py N` 确认它真的已合并，不要假设。然后：

1. `timeout 90 git fetch origin main`（或用 HTTPS 地址），再 `git merge --ff-only origin/main`。确认没有冲突标记：`rg "^(<<<<<<<|>>>>>>>)" CHANGELOG.md`。工作区有未提交的改动时，快进通常不受影响，但要看一眼输出。
2. 用完整 SHA 查新 `main` 的 CI；还在运行就如实汇报，不要在循环里空等。
3. 跑快测；涉及对应区域时再跑集成测试和前端构建。
4. 确认已合并（`git merge-base --is-ancestor`）并征得同意后，再删除 worktree 和本地分支（`verify_pr.sh` 默认已清理）。
5. 为每个 PR 起草致谢评论，写清验证了什么，以及可选的后续小改进。
6. CHANGELOG：贡献者把条目加在 `[Unreleased]` 下。发版时改成 `[x.y.z] - 日期`，并保留一个空的 `[Unreleased]`；同步升级 `pyproject.toml`、`main.py`、`package.json`、`package-lock.json`（两处）和 compose 的镜像标签，然后运行 `release_check.py --tag vX.Y.Z`。
7. 提交：仓库的 git 不支持 `--trailer` 时，可用底层命令：`git add -A; T=$(git write-tree); C=$(git commit-tree "$T" -p HEAD -F msg.txt); git update-ref refs/heads/main "$C"`。只有维护者要求或已委托发版时才推送。
8. 打 tag 会向 ghcr 发布镜像，且无法撤回：必须等 `main` 的 CI 全绿后再推 tag。发布流程最多查几次状态，然后把进度和 Actions 链接交还维护者，不要无限轮询。

## 给 AI 助手的操作习惯

- 修改文件和读取该文件的命令不要放在同一批并行调用里，否则命令可能先于修改执行，看到旧结果。
- 开始验证前记录开发服务状态（`./service.sh status`），结束后恢复。
- 做完后清理所有临时资源：worktree、分支、一次性库、临时 Key、token 文件、临时端口的进程。

## 各工具的入口

正文只维护在本目录，下面的入口都只是指向这里，改流程只改本目录：

- Cursor、Codex 等遵循 `AGENTS.md` 约定的工具：根目录 `AGENTS.md`
- Claude Code：`CLAUDE.md` 里的「处理 PR」一节
- 其他工具：对助手说「按 `docs/maintainers/handle-pr/README.md` 处理这个 PR」

## 维护记录

每处理完一个 PR，把实际碰到的问题和更好的做法补进上面的流程或清单，并在这里记一行：日期、PR、改了什么。

- 2026-11-04，PR #1、#2：初版。覆盖获取、分诊、本地验证、合并顺序、合并后收尾和发版。
- 2026-11-05，PR #3：补充「是否是对之前评论的跟进」「先读测试再读实现」「基线数量对账」「新增状态值」清单；记录 worktree 里没有 `.env` 和 `node_modules` 时的做法、在 5003 端口起 PR 版后端对真实渠道验证、按 PID 停进程。
- 2026-11-05，客户端实测后补测试：实测中发现的行为（例如联网搜索透传）要补成回归测试再改代码，先让测试失败再让它通过；测试数量对账时要考虑本地已构建前端会多一条路由守卫用例。
- 2026-11-05，结构整理：新增 `scripts/pr_info.py` 和 `scripts/verify_pr.sh`，把重复的手工命令固化；真实渠道验证拆到 `real-channel.md`；`pr_info.py` 对已合并的 PR 不再提示「需要 Update branch」；`verify_pr.sh` 在判断不出改动文件时全部步骤都跑。
- 2026-11-07，文档整理：`real-channel.md` 并回本文「真实渠道验证」一节，`ROADMAP.md` 移到 `docs/`。
