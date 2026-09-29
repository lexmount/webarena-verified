# CI 与自动审查

`test.yml` 对所有 pull request 执行 lint、类型检查和单元测试；向 `main` 或 `lex-main` 推送时也会执行。这样以 `lex-main` 为目标分支的 fork 修复 PR 与上游 `main` PR 使用同一套代码门禁。

`claude.yml` 是仓库级中文审查：非 Draft PR 在创建、更新、重新打开或转为 ready 时自动运行，也支持在 issue、PR 评论和 review 中通过 `@claude` 触发交互任务。第三方 action 固定到具体提交，工作流只读取仓库内容，并仅保留发布 PR/issue 评论所需的写权限。

仓库级工作流与 Lexmount 组织级 `Auto Code Review - Claude` 相互独立。组织规则命中的 PR 会同时出现两套 review；仓库工作流不取消、替代或复用组织级运行。
