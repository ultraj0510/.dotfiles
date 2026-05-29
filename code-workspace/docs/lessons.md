# Lessons

Shared lessons for Codex and Claude Code work in `/Users/fujie/code`.

Tool-specific lessons may point here instead of duplicating content.

## 2026-05-29

### SBI auth: JSESSIONID domain matters
- SBI JSESSIONID is hostOnly for `site1.sbisec.co.jp`. Using `www.sbisec.co.jp` URLs causes cookies to never be sent.
- Fix: all SBI page access URLs must use `site1.sbisec.co.jp`.

### Report generation: same-ticker multi-position handling
- portfolio.yaml can have multiple positions for the same ticker (現物×N, 信用×N).
- Never use `dict[ticker] = position` for lookups — use list iteration.
- Verify position count matches between portfolio.yaml and report before claiming completion.

### Cookie store: semicolon splitting
- Raw cookie strings use `; ` (semicolon-space) as separator, not just `;`.
- `read_cookie_objects()` must handle both raw cookie strings and JSON arrays.
