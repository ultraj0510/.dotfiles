# Code Workspace Dotfiles Ownership Plan

## Decision

Option B: Move workspace config into `/Users/fujie/.dotfiles/code-workspace` and symlink back.

## Rationale

Workspace config (`AGENTS.md`, `CLAUDE.md`, `workspace.md`, `workspace.toml`, `ai/`, `docs/plans/`, `docs/lessons.md`) behaves like personal environment configuration and should live with dotfiles. Project repos (`playground`, `learning-ddd`, `references/claude-code-best-practice`) remain independent.

## Files to Move

```
/Users/fujie/code/AGENTS.md          → /Users/fujie/.dotfiles/code-workspace/AGENTS.md
/Users/fujie/code/CLAUDE.md          → /Users/fujie/.dotfiles/code-workspace/CLAUDE.md
/Users/fujie/code/workspace.md       → /Users/fujie/.dotfiles/code-workspace/workspace.md
/Users/fujie/code/workspace.toml     → /Users/fujie/.dotfiles/code-workspace/workspace.toml
/Users/fujie/code/ai/                → /Users/fujie/.dotfiles/code-workspace/ai/
/Users/fujie/code/docs/plans/        → /Users/fujie/.dotfiles/code-workspace/docs/plans/
/Users/fujie/code/docs/lessons.md    → /Users/fujie/.dotfiles/code-workspace/docs/lessons.md
/Users/fujie/code/docs/archive/      → /Users/fujie/.dotfiles/code-workspace/docs/archive/
```

## Symlinks (back to /Users/fujie/code)

```bash
ln -sf /Users/fujie/.dotfiles/code-workspace/AGENTS.md /Users/fujie/code/AGENTS.md
ln -sf /Users/fujie/.dotfiles/code-workspace/CLAUDE.md /Users/fujie/code/CLAUDE.md
ln -sf /Users/fujie/.dotfiles/code-workspace/workspace.md /Users/fujie/code/workspace.md
ln -sf /Users/fujie/.dotfiles/code-workspace/workspace.toml /Users/fujie/code/workspace.toml
ln -sf /Users/fujie/.dotfiles/code-workspace/ai /Users/fujie/code/ai
ln -sf /Users/fujie/.dotfiles/code-workspace/docs/plans /Users/fujie/code/docs/plans
ln -sf /Users/fujie/.dotfiles/code-workspace/docs/lessons.md /Users/fujie/code/docs/lessons.md
ln -sf /Users/fujie/.dotfiles/code-workspace/docs/archive /Users/fujie/code/docs/archive
```

## Rollback

```bash
rm /Users/fujie/code/AGENTS.md /Users/fujie/code/CLAUDE.md /Users/fujie/code/workspace.md /Users/fujie/code/workspace.toml
cp -r /Users/fujie/.dotfiles/code-workspace/* /Users/fujie/code/
rm /Users/fujie/code/ai /Users/fujie/code/docs/plans /Users/fujie/code/docs/lessons.md /Users/fujie/code/docs/archive
cp -r /Users/fujie/.dotfiles/code-workspace/ai /Users/fujie/.dotfiles/code-workspace/docs /Users/fujie/code/
```

## Prerequisites

- `.dotfiles` repo is clean before starting
- No tool has open handles on the target files during move
- Claude Code and Codex both follow symlinks for entrypoint files
