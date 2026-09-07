# Codex Workspace Entrypoint

Human-oriented shared guidance lives in `/Users/fujie/code/workspace.md`.
Machine-readable structure, paths, defaults, commands, and rule values live in
`/Users/fujie/code/workspace.toml`.

## Codex-specific notes

- Use `/Users/fujie/code/workspace.md` for shared behavioral guidance and responsibilities.
- Use `/Users/fujie/code/workspace.toml` as the authority for machine-readable workspace facts.
- Prefer `.codex/` only for Codex-specific agent/config files.
- Do not duplicate Claude-only instructions here unless Codex needs different behavior.
- 任务记录与 `taskctl` 的适用范围统一遵循 `workspace.md` 的“任务治理适用范围”；不因任务非平凡就强制所有仓库登记。
- 使用 `taskctl` 管理的任务不手写 `COMPLETE`，由 `taskctl close` 推导；其他任务按实际验收证据报告结果。
