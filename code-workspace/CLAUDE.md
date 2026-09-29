# Claude Code 工作区入口

面向人的共享指南见 `/Users/fujie/code/workspace.md`，机器可判定的结构、路径、默认值、命令和规则值见
`/Users/fujie/code/workspace.toml`。系统概览见 `/Users/fujie/code/README.md`。

## Claude 专属说明

- 使用 `/Users/fujie/code/workspace.md` 理解共享行为指南和职责边界。
- 以 `/Users/fujie/code/workspace.toml` 作为机器可读工作区事实的权威来源。
- `.claude/` 仅用于 Claude 专属的代理、规则、钩子和本地设置。
- 除非 Claude 需要不同的行为，否则不要在此处重复 Codex 专属的指令。
- 任务记录与 `taskctl` 的适用范围统一遵循 `workspace.md` 的“任务治理适用范围”；不因任务非平凡就强制所有仓库登记。
- 使用 `taskctl` 管理的任务不手写 `COMPLETE`，由 `taskctl close` 推导；其他任务按实际验收证据报告结果。
