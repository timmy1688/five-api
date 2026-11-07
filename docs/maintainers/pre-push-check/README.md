---
name: pre-push-leak-check
description: 推送代码前检查本次要推送的提交和截图里有没有密钥、真实凭据、个人信息等敏感信息泄露。用户说"推送""push""提交并推送"、发版打 tag、或让检查泄密/敏感信息时使用。
---

# 推送前泄密检查（five-api）

仓库是公开的，推上去的内容（包括提交作者邮箱和截图）就收不回来了。每次推送前跑一遍；用户让你"推送"时，先检查再推。

给 AI 助手的约定：回复使用中文，先给结论（能推 / 不能推），再列问题和处理办法。不要在回复、日志、提交信息里写出任何命中的密钥原文。

## 流程

```
- [ ] 1 跑扫描脚本
- [ ] 2 逐条判断 BLOCK / WARN
- [ ] 3 打开每张新增或修改的图片
- [ ] 4 看一眼本次 diff 里扫描规则覆盖不到的内容
- [ ] 5 给结论；有 BLOCK 时不推送
```

### 1. 扫描

在仓库根目录执行：

```bash
python docs/maintainers/pre-push-check/scripts/leak_check.py              # 待推送的提交 @{upstream}..HEAD
python docs/maintainers/pre-push-check/scripts/leak_check.py --worktree   # 还没提交时，连同工作区和未跟踪文件
python docs/maintainers/pre-push-check/scripts/leak_check.py --history    # 全部历史（发版前或怀疑泄露时）
```

脚本只用标准库，检查：

- 新增代码行里的密钥格式：私钥、AWS、GitHub、GitLab、Slack、Google、Anthropic、OpenAI 风格 Key、阿里云 AccessKey、JWT、带密码的连接串、飞书/钉钉机器人地址、`password = "..."` 类赋值。
- 本地真实密钥：把 `.env`、`data/secrets.json` 里的值和待推送内容逐个比对，只报来源字段，不打印值。
- 敏感文件：`.env*`（`.env.example` 除外）、`data/`、`secrets.json`、私钥证书、数据库和备份文件。
- 个人信息：提交作者/提交者邮箱、手机号、通过校验位的身份证号、公网 IP、非示例邮箱。
- 新增或修改的图片：列出来，需要人工看。

退出码 1 表示有 BLOCK。

### 2. 判断

| 级别 | 含义 | 处理 |
| --- | --- | --- |
| BLOCK | 真实密钥格式、本地密钥值、敏感文件 | 不推送。从提交里移除后重新扫描 |
| WARN | 测试路径里的密钥格式、个人信息、提交邮箱 | 逐条确认；是假数据或有意公开的可以推 |
| REVIEW | 图片 | 必须打开看 |

- **测试里的假密钥**：测试路径下命中只报 WARN。确认是虚构值即可；优先用 `AKIAIOSFODNN7EXAMPLE` 这类公认示例，或在该行加 `# leak-check: allow`。
- **误报**：确认不是密钥后，在该行加 `leak-check: allow` 注释，不要放宽脚本规则来让它通过。
- **提交邮箱**：作者邮箱是 QQ 号、公司邮箱时会在 GitHub 上公开。还没推送的提交可以用 `git commit --amend --reset-author`（或对多个提交 `git rebase -i` 后逐个 amend）改掉；以后设置 `git config user.email "<id>+<name>@users.noreply.github.com"`。已经推上去的历史不要为此改写。

### 3. 图片

用 Read 工具打开每张图，检查：

- 真实客户名、租户用户名、手机号、邮箱、身份证号
- 完整或可还原的 Key、上游地址（应为 `example.com` 一类）、内网 IP、真实金额
- 浏览器地址栏、书签栏、终端窗口里的主机名和路径

截图用 Playwright 拦截 `/api/**` 返回演示数据来生成，不用真实环境截。

### 4. 规则覆盖不到的

快速浏览 `git diff @{upstream}..HEAD` 的非测试部分，留意：

- 新加的日志、报错、接口响应会不会带出上游 Key、请求原文、密码、临时密码
- 文档和文章里的真实姓名、公司、工作地址、内网域名、服务器 IP
- 新增的示例配置是不是从本地环境直接复制的

### 5. 结论

```
结论：可以推送 / 不能推送

扫描范围：origin/main..HEAD（N 个提交）
BLOCK：无 / 列出文件和处理办法
WARN：逐条说明为什么可以接受，或需要怎么改
图片：已查看 X 张，无真实数据 / 问题
```

## 已经推上去了怎么办

1. **先作废密钥**：在对应平台吊销并换新（上游 Key、GitHub Token、`data/secrets.json` 里的 JWT 密钥要轮换；加密密钥按 `docs/OPERATIONS.md` 用 `migrate_secrets` 迁移）。改写历史救不回已经被抓取的密钥。
2. 再删除：新提交里移除文件或内容，并把文件加进 `.gitignore`。
3. 是否改写历史由维护者决定。仓库在 dromara 组织下，强制推送会影响所有 fork 和协作者，需要先和组织沟通。
