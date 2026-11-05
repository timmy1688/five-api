# 评论模板

用贡献者提交 PR 时使用的语言回复（看 PR 正文判断）。写具体：说明验证了什么、没能验证什么。后续建议要标明是可选的。不承诺发布日期。

## 已合并：致谢

还没发版时，不要写版本链接，把第一句改成「已合并，会随下一个版本发布」（英文：`merged, and it will ship in the next release`）。发版后再补一条链接。

中文：

```markdown
感谢 @<作者>，已合并，并随 [<版本>](<Release 链接>) 发布。

<一两句说明设计或测试里值得肯定的地方。>

发布前我验证了：

- <真实客户端或端到端检查及结果>
- <测试数量，例如“集成测试 23 项全过”>

<没能验证的部分，例如“X 没法在真实上游复现，只由你的单元测试覆盖”。>

<可选的后续建议：一条具体建议，不强求。>
```

English:

```markdown
Thanks @<author>, merged and released in [<version>](<release url>).

<One or two sentences on what is good about the design or tests.>

What I checked before releasing:

- <real-client or end-to-end check and its result>
- <test suite counts, for example "integration suite (23 tests) passes">

<What could not be verified, for example "I could not trigger X on a real upstream, so that path is covered by your unit tests only.">

<Optional follow-up: one concrete suggestion, "no pressure".>
```

## 需要修改后再合并

```markdown
感谢提交，@<作者>。方向没问题，合并前希望调整下面几点：

**必须改**

1. <文件:行号，问题是什么，为什么重要，建议的改法>

**建议改（可以放到后续 PR）**

- <建议>

我跑过的验证：<命令和结果>。你更新后我会再检查一遍。
```

## 超出范围，不合并

```markdown
感谢你花时间提交，@<作者>。这个 PR 我先关闭，原因是：<一条具体理由，例如“它属于 ROADMAP「不做」一节里的 <条目>”>。

<如有帮助：怎样的类似改动是可以接受的，或者指向一个适合新手的任务。>
```

## 分支落后或有冲突

```markdown
main 已经更新（<PR 或提交> 改了 `CHANGELOG.md`）。麻烦点一下 "Update branch"，或者 rebase 到 main。预计唯一的冲突在 `CHANGELOG.md` 的 `[Unreleased]` 段，两边的条目都保留即可。
```

## 给维护者的合并步骤

1. 打开 PR 页面，拉到最下面的框。
2. 确认显示 "No conflicts with base branch"，检查项都是绿色。
3. 点绿色的 Merge pull request，选 Create a merge commit，再点 Confirm merge。
4. 合并后告诉 AI，让它拉取代码、检查 CI 并跑测试。
