# Codex 与 Claude 个人规则统一设计

## 目标

将用户提供的 417 行个人工作规则完整纳入 dotfiles，并让 Codex 与 Claude Code
在所有仓库中加载同一份规则。项目级说明继续只承载项目事实与局部约束，不复制个人规则。

## 范围

- 新增一份 Git 管理的个人规则权威源，内容与用户附件一致。
- 通过安装脚本将该权威源链接为 `~/.codex/AGENTS.md`，供 Codex 全局加载。
- 在 `~/.claude/CLAUDE.md` 的 dotfiles 源文件中导入同一权威源，同时保留现有
  Claude 专属股票分析说明。
- 修正工作区共享说明中与新个人规则冲突的“内部源码标识使用中文”规则，使其与
  “源码标识默认使用英文”一致。
- 更新 dotfiles 说明与回归测试，覆盖权威源、两个加载入口和安装链接。

## 非目标

- 不修改股票分析流程、技能、插件、权限或代理定义。
- 不重写项目级 `AGENTS.md`、`CLAUDE.md` 的薄入口结构。
- 不压缩、改写或重新解释用户提供的个人规则。
- 不引入生成器、Schema 或新的配置系统。

## 设计

### 单一权威源

新增 `agent-guidance/personal-workstyle.md`，逐字保存用户批准的个人规则，仅增加
Git 文本文件的标准 EOF 换行。Codex 与 Claude 不各自维护副本，避免后续规则漂移。

### Codex 加载

`install.sh` 使用现有 `backup_and_link` 流程创建：

```text
~/.codex/AGENTS.md -> ~/.dotfiles/agent-guidance/personal-workstyle.md
```

已有正确链接时保持幂等；已有普通文件时先备份；已有指向其他来源的符号链接时
fail closed，不覆盖来源不明的配置。

### Claude Code 加载

`claude/CLAUDE.md` 在顶部使用用户级导入：

```text
@~/.dotfiles/agent-guidance/personal-workstyle.md
```

用该导入替换现有 `<!-- User customizations -->` 下已被新规则覆盖且存在冲突的旧摘要。
项目级 `code-workspace/CLAUDE.md` 中的 Claude 专属股票分析系统说明保持不变。
Claude 用户级导入不要求项目级外部文件审批。

### 项目规则冲突

`code-workspace/workspace.md` 仍是项目共享指南，但其中内部源码标识语言规则改为：
变量名、函数名、类型名和模块名默认使用英文；外部协议及兼容性敏感标识保持规定形式。
不修改 `workspace.toml` 的 `commit_language = "zh"`，因为提交信息继续默认使用中文。

## 失败处理与回滚

- 安装源缺失、相对链接无法解析或目标是未知符号链接时，沿用 `backup_and_link`
  的阻断语义。
- 回滚代码只需撤销本次提交；若已运行安装脚本，可将
  `~/.codex/AGENTS.md` 删除并从时间戳备份目录恢复原文件。
- 不自动替换来源不明的现有 Codex 全局链接。

## 验证

- 校验个人规则权威源除标准 EOF 换行外与附件内容完全一致。
- 校验 Claude 用户级文件导入权威源，且旧个人规则摘要已移除。
- 在临时目录中执行安装器现有 `backup_and_link` 函数，确认 Codex 链接创建与
  重复执行幂等，并确认冲突符号链接被阻断。完整安装在变更进入持久主工作区后执行，
  避免绕过 linked worktree 的永久链接保护。
- 执行 shell 语法检查、dotfiles 相关 pytest、工作区 preflight。
- 检查真实 diff，确认没有修改任务范围外文件。

## 完成条件

- Codex 与 Claude 的全局入口解析到同一份个人规则。
- 个人规则与附件逐字一致。
- 工作区不存在与源码标识语言有关的活动规则冲突。
- 定向测试、完整 dotfiles 测试与 preflight 均有当前工作树证据。
