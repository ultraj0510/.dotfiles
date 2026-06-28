# Claude Code Workspace Entrypoint

Shared workspace rules live in `/Users/fujie/code/workspace.md`. System overview in `/Users/fujie/code/README.md`.

## Claude-specific notes

- Use `/Users/fujie/code/workspace.md` as the source of truth for project structure and shared rules.
- Prefer `.claude/` only for Claude-specific agents, rules, hooks, and local settings.
- Do not duplicate Codex-only instructions here unless Claude needs different behavior.

## Stock Analysis System

Skills live under `~/.dotfiles/claude/skills/`. The two main entry points:

### Daily workflow (`stock-advisor`)

1. User runs `/portfolio-auth` to ensure valid SBI cookies
2. User runs `/portfolio-fetch` to refresh portfolio data
3. User runs `/stock-advisor` which internally:
   - Calls `run_daily_actions.py` → subprocess `stock-company-analyze` per ticker
   - `stock-company-analyze` runs its 7-phase pipeline → `analysis.json` per ticker
   - `portfolio_helper.py` overlays portfolio constraints (margin, credit expiry, concentration)
   - Outputs `daily_actions.json` and `report.md`

### Deep analysis (`stock-company-analyze`)

Standalone single-ticker analysis. Use `/stock-company-analyze <ticker>`.
Produces `analysis.json` v2.0 with technical, fundamental, integrated, and forecast blocks.

### Key constraints

- stock-advisor knows portfolio/watchlist/account/report — never recalculates technicals or forecasts
- stock-company-analyze knows evidence/technical/fundamental/forecast only — never reads portfolio
- All schema changes are additive (v2.0 adds blocks, v1.0 consumers unaffected)
- Tests: stock-advisor 220 tests, stock-company-analyze 88 tests — run before committing

### Skill invocation rules

- Use the `Skill` tool to invoke skills — never read SKILL.md manually
- stock-advisor requires `portfolio-fetch` to have been run beforehand
- stock-company-analyze is also callable as a subprocess from `run_daily_actions.py`
