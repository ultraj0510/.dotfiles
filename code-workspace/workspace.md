# code workspace

## Workspace Manifest

Machine-readable workspace paths live in `/Users/fujie/code/workspace.toml`.
When a path changes, update `workspace.toml` first, then update prose docs and generated files.

## Purpose

This workspace supports Japanese stock analysis, portfolio management, automation skills, and agent workflow experiments.

Codex and Claude Code are both expected to operate here. Shared rules live in this file. Tool-specific entrypoints should stay thin.

## Primary Areas

| Path | Purpose |
|------|---------|
| `/Users/fujie/code/playground/stock-price-analyze` | Current stock analysis implementation. Future candidate for `/Users/fujie/code/projects/stock-price-analyze`. |
| `/Users/fujie/.dotfiles/portfolio-core` | Shared SBI portfolio auth/fetch implementation used by Claude and agent wrappers. |
| `/Users/fujie/.dotfiles/claude/skills` | Git-managed Claude skill definitions. |
| `/Users/fujie/.agents/skills` | Agent runtime skill mirror. Should not be treated as the source of truth. |
| `/Users/fujie/code/ai` | Workspace-local source definitions for dual Codex/Claude agents. |
| `/Users/fujie/code/docs` | Plans, lessons, and reviews. |
| `/Users/fujie/code/references/claude-code-best-practice` | External reference material for Claude Code/Codex workflows. |
| `/Users/fujie/code/runtime` | Generated state and run outputs that are not source code. |
| `/Users/fujie/code/scratch` | Temporary experiments. |

## Shared Rules

- Respond to the user in Japanese.
- Commit messages and code comments are written in English.
- Security-sensitive files, credentials, brokerage Cookies, and personal portfolio data must not be committed.
- For non-trivial work, write or update a plan before implementation.
- Prefer one source of truth and generated tool-specific files over duplicated manual definitions.
- Do not move files across git repository boundaries without checking `git status` and recording the rollback path.
- Generated daily analysis outputs belong under `runtime/` or ignored result directories, not mixed with source unless explicitly curated as fixtures.
- Claude Code automatically loads `~/.claude/CLAUDE.md` for user-level rules. This workspace file covers project-level rules only.
