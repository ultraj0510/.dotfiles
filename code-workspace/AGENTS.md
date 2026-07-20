# Codex Workspace Entrypoint

Human-oriented shared guidance lives in `/Users/fujie/code/workspace.md`.
Machine-readable structure, paths, defaults, commands, and rule values live in
`/Users/fujie/code/workspace.toml`.

## Codex-specific notes

- Use `/Users/fujie/code/workspace.md` for shared behavioral guidance and responsibilities.
- Use `/Users/fujie/code/workspace.toml` as the authority for machine-readable workspace facts.
- Prefer `.codex/` only for Codex-specific agent/config files.
- Do not duplicate Claude-only instructions here unless Codex needs different behavior.
- 非平凡任务从 `templates/task.md` 创建定义，并运行 `scripts/taskctl start <task-file>`。
- 不手写 `COMPLETE`；使用 `scripts/taskctl close <task-file> --evidence <evidence-file>` 重新推导结论。
