# Workspace Git Management Next Steps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codex と Claude Code が同じ `/Users/fujie/code` ワークスペースを使いながら、変更の所有repo・コミット順・個人データの扱いを明確にする。

**Architecture:** `/Users/fujie/code` はプロジェクトrepoを束ねる作業場として扱い、ワークスペース設定は `/Users/fujie/.dotfiles` の `code-workspace/` に寄せる。`playground`・`learning-ddd`・`references/claude-code-best-practice` は独立repoとして残し、個人資産データと生成物は通常コミットから分離する。

**Tech Stack:** git, Python 3, Codex AGENTS.md, Claude CLAUDE.md, generated agents, workspace.toml

---

## Current State Snapshot

- `/Users/fujie/code` は git repo ではない: `NO_GIT:/Users/fujie/code`
- `/Users/fujie/code/ai/checks/check_workspace.py` は成功: `workspace hygiene ok`
- `/Users/fujie/code/ai/tools/sync_agents.py` は成功: `Synced 7 agents.`
- `/Users/fujie/code/references/claude-code-best-practice` は clean
- `/Users/fujie/.dotfiles` は portfolio-auth / portfolio-fetch / portfolio-core の変更が未コミット
- `/Users/fujie/code/playground` は hygiene変更と個人データ変更が混在
- `/Users/fujie/code/learning-ddd` は `chapter-6.md` が未追跡

## Git Ownership Decision

採用方針: `/Users/fujie/code` 直下には新しい git repo を作らず、ワークスペース設定は `/Users/fujie/.dotfiles/code-workspace` で管理する。

理由:

- `/Users/fujie/code` は `playground`・`learning-ddd`・`references/claude-code-best-practice` のような既存repoを内包しているため、親repo化すると nested repo / submodule 境界が曖昧になる。
- `AGENTS.md`・`CLAUDE.md`・`workspace.md`・`workspace.toml`・`ai/` は個人作業環境の設定であり、`.dotfiles` の管理対象にする方が自然。
- `runtime/`・`scratch/`・SBI証券由来の `portfolio.yaml`・分析reportは、通常の設定コミットから分離する必要がある。

## File Responsibility Map

- `/Users/fujie/.dotfiles/portfolio-core/`: SBI認証・Cookie保存・取得ロジックの実装本体
- `/Users/fujie/.dotfiles/claude/skills/portfolio-auth/`: Claude向け portfolio-auth skill
- `/Users/fujie/.dotfiles/claude/skills/portfolio-fetch/`: Claude向け portfolio-fetch skill
- `/Users/fujie/.dotfiles/tests/test_portfolio_auth_cookie_refresh.py`: Cookie更新問題の回帰テスト
- `/Users/fujie/.dotfiles/code-workspace/`: 今後のワークスペース設定のgit管理先
- `/Users/fujie/code/AGENTS.md`: `.dotfiles/code-workspace/AGENTS.md` へのsymlink候補
- `/Users/fujie/code/CLAUDE.md`: `.dotfiles/code-workspace/CLAUDE.md` へのsymlink候補
- `/Users/fujie/code/workspace.md`: `.dotfiles/code-workspace/workspace.md` へのsymlink候補
- `/Users/fujie/code/workspace.toml`: `.dotfiles/code-workspace/workspace.toml` へのsymlink候補
- `/Users/fujie/code/ai/`: `.dotfiles/code-workspace/ai` へのsymlink候補
- `/Users/fujie/code/docs/plans/`: `.dotfiles/code-workspace/docs/plans` へのsymlink候補
- `/Users/fujie/code/playground/.gitignore`: playground repoの作業生成物除外
- `/Users/fujie/code/playground/stock-price-analyze/.gitignore`: stock-price-analyze結果出力の除外
- `/Users/fujie/code/playground/stock-price-analyze/portfolio.yaml`: 個人ポートフォリオ実データ。通常コミット対象から外す候補
- `/Users/fujie/code/playground/stock-price-analyze/results/`: 分析生成物。通常コミット対象から外す候補

---

### Task 1: Freeze Current Git State Before Editing

**Files:**
- Read: `/Users/fujie/.dotfiles`
- Read: `/Users/fujie/code/playground`
- Read: `/Users/fujie/code/references/claude-code-best-practice`
- Read: `/Users/fujie/code/learning-ddd`

- [ ] **Step 1: Record repo boundaries**

Run:

```bash
git -C /Users/fujie/code rev-parse --show-toplevel 2>/dev/null || printf 'NO_GIT:/Users/fujie/code\n'
git -C /Users/fujie/.dotfiles rev-parse --show-toplevel
git -C /Users/fujie/code/playground rev-parse --show-toplevel
git -C /Users/fujie/code/references/claude-code-best-practice rev-parse --show-toplevel
git -C /Users/fujie/code/learning-ddd rev-parse --show-toplevel
```

Expected:

```text
NO_GIT:/Users/fujie/code
/Users/fujie/.dotfiles
/Users/fujie/code/playground
/Users/fujie/code/references/claude-code-best-practice
/Users/fujie/code/learning-ddd
```

- [ ] **Step 2: Record dirty state**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short
git -C /Users/fujie/code/playground status --short
git -C /Users/fujie/code/references/claude-code-best-practice status --short
git -C /Users/fujie/code/learning-ddd status --short
```

Expected:

```text
 M claude/skills/portfolio-auth/SKILL.md
 M claude/skills/portfolio-auth/auth_sbi.py
 M claude/skills/portfolio-fetch/scripts/fetch_portfolio.py
 M portfolio-core/cookie_store.py
 M portfolio-core/sbi_auth.py
 M portfolio-core/sbi_fetch.py
?? tests/
 D .DS_Store
 M stock-price-analyze/.gitignore
 M stock-price-analyze/portfolio.yaml
 M stock-price-analyze/results/2026-05-28/report.md
?? .gitignore
?? chapter-6.md
```

- [ ] **Step 3: Stop if unexpected repo state appears**

If any additional modified file appears, write its path into this plan under "Review Notes" before continuing. Do not stage unknown files in later tasks.

---

### Task 2: Commit Portfolio Auth Fixes In Dotfiles

**Files:**
- Modify: `/Users/fujie/.dotfiles/portfolio-core/cookie_store.py`
- Modify: `/Users/fujie/.dotfiles/portfolio-core/sbi_auth.py`
- Modify: `/Users/fujie/.dotfiles/portfolio-core/sbi_fetch.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/portfolio-auth/SKILL.md`
- Modify: `/Users/fujie/.dotfiles/claude/skills/portfolio-auth/auth_sbi.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/portfolio-fetch/scripts/fetch_portfolio.py`
- Create: `/Users/fujie/.dotfiles/tests/test_portfolio_auth_cookie_refresh.py`

- [ ] **Step 1: Remove generated Python caches from tests**

Run:

```bash
find /Users/fujie/.dotfiles/tests -name '__pycache__' -type d -prune -exec rm -rf {} +
find /Users/fujie/.dotfiles/tests -name '.pytest_cache' -type d -prune -exec rm -rf {} +
```

Expected:

```text
```

- [ ] **Step 2: Verify no generated cache remains in tests**

Run:

```bash
find /Users/fujie/.dotfiles/tests \( -name '__pycache__' -o -name '.pytest_cache' \) -print
```

Expected:

```text
```

- [ ] **Step 3: Compile changed Python files**

Run:

```bash
python3 -m py_compile \
  /Users/fujie/.dotfiles/portfolio-core/cookie_store.py \
  /Users/fujie/.dotfiles/portfolio-core/sbi_auth.py \
  /Users/fujie/.dotfiles/portfolio-core/sbi_fetch.py \
  /Users/fujie/.dotfiles/claude/skills/portfolio-auth/auth_sbi.py \
  /Users/fujie/.dotfiles/claude/skills/portfolio-fetch/scripts/fetch_portfolio.py
```

Expected:

```text
```

- [ ] **Step 4: Run the new cookie refresh regression test**

Run:

```bash
pytest -q /Users/fujie/.dotfiles/tests/test_portfolio_auth_cookie_refresh.py
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Run the existing SBI smoke test if credentials are not required**

Run:

```bash
python3 /Users/fujie/code/tasks/test_portfolio_sbi.py
```

Expected:

```text
The command either completes without traceback or exits with a clear message that live SBI credentials/session are required.
```

- [ ] **Step 6: Review the staged scope**

Run:

```bash
git -C /Users/fujie/.dotfiles diff --stat
git -C /Users/fujie/.dotfiles status --short
```

Expected:

```text
Only portfolio-auth, portfolio-fetch, portfolio-core, and tests/test_portfolio_auth_cookie_refresh.py are listed.
```

- [ ] **Step 7: Commit portfolio auth fixes**

Run:

```bash
git -C /Users/fujie/.dotfiles add \
  claude/skills/portfolio-auth/SKILL.md \
  claude/skills/portfolio-auth/auth_sbi.py \
  claude/skills/portfolio-fetch/scripts/fetch_portfolio.py \
  portfolio-core/cookie_store.py \
  portfolio-core/sbi_auth.py \
  portfolio-core/sbi_fetch.py \
  tests/test_portfolio_auth_cookie_refresh.py
git -C /Users/fujie/.dotfiles commit -m "fix: harden SBI cookie refresh handling"
```

Expected:

```text
[branch commit] fix: harden SBI cookie refresh handling
```

---

### Task 3: Commit Playground Hygiene Separately

**Files:**
- Create: `/Users/fujie/code/playground/.gitignore`
- Modify: `/Users/fujie/code/playground/stock-price-analyze/.gitignore`
- Remove from git: `/Users/fujie/code/playground/.DS_Store`
- Do not stage: `/Users/fujie/code/playground/stock-price-analyze/portfolio.yaml`
- Do not stage: `/Users/fujie/code/playground/stock-price-analyze/results/2026-05-28/report.md`

- [ ] **Step 1: Confirm playground status before staging**

Run:

```bash
git -C /Users/fujie/code/playground status --short
```

Expected:

```text
 D .DS_Store
 M stock-price-analyze/.gitignore
 M stock-price-analyze/portfolio.yaml
 M stock-price-analyze/results/2026-05-28/report.md
?? .gitignore
```

- [ ] **Step 2: Stage only hygiene files**

Run:

```bash
git -C /Users/fujie/code/playground add .gitignore stock-price-analyze/.gitignore
git -C /Users/fujie/code/playground rm --cached .DS_Store
```

Expected:

```text
rm '.DS_Store'
```

- [ ] **Step 3: Verify personal data is unstaged**

Run:

```bash
git -C /Users/fujie/code/playground diff --cached --name-only
git -C /Users/fujie/code/playground diff --name-only
```

Expected:

```text
.DS_Store
.gitignore
stock-price-analyze/.gitignore
stock-price-analyze/portfolio.yaml
stock-price-analyze/results/2026-05-28/report.md
```

Interpretation: the first command must list only `.DS_Store`, `.gitignore`, and `stock-price-analyze/.gitignore`. The second command should still list `stock-price-analyze/portfolio.yaml` and `stock-price-analyze/results/2026-05-28/report.md`.

- [ ] **Step 4: Commit playground hygiene**

Run:

```bash
git -C /Users/fujie/code/playground commit -m "chore: ignore generated workspace state"
```

Expected:

```text
[branch commit] chore: ignore generated workspace state
```

---

### Task 4: Move Workspace Config Ownership To Dotfiles

**Files:**
- Create: `/Users/fujie/.dotfiles/code-workspace/AGENTS.md`
- Create: `/Users/fujie/.dotfiles/code-workspace/CLAUDE.md`
- Create: `/Users/fujie/.dotfiles/code-workspace/workspace.md`
- Create: `/Users/fujie/.dotfiles/code-workspace/workspace.toml`
- Create: `/Users/fujie/.dotfiles/code-workspace/ai/`
- Create: `/Users/fujie/.dotfiles/code-workspace/docs/plans/`
- Create: `/Users/fujie/.dotfiles/code-workspace/docs/lessons.md`
- Create: `/Users/fujie/.dotfiles/code-workspace/docs/archive/`
- Replace with symlink: `/Users/fujie/code/AGENTS.md`
- Replace with symlink: `/Users/fujie/code/CLAUDE.md`
- Replace with symlink: `/Users/fujie/code/workspace.md`
- Replace with symlink: `/Users/fujie/code/workspace.toml`
- Replace with symlink: `/Users/fujie/code/ai`
- Replace with symlink: `/Users/fujie/code/docs/plans`
- Replace with symlink: `/Users/fujie/code/docs/lessons.md`
- Replace with symlink: `/Users/fujie/code/docs/archive`

- [ ] **Step 1: Ensure dotfiles is clean after Task 2**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short
```

Expected:

```text
```

- [ ] **Step 2: Create only the destination parent directory**

Run:

```bash
mkdir -p /Users/fujie/.dotfiles/code-workspace/docs
```

Expected:

```text
```

- [ ] **Step 3: Move workspace-owned files into dotfiles**

The destination directories `plans` and `archive` must not exist before this step; `mv` should create them by moving the current directories.

Run:

```bash
mv /Users/fujie/code/AGENTS.md /Users/fujie/.dotfiles/code-workspace/AGENTS.md
mv /Users/fujie/code/CLAUDE.md /Users/fujie/.dotfiles/code-workspace/CLAUDE.md
mv /Users/fujie/code/workspace.md /Users/fujie/.dotfiles/code-workspace/workspace.md
mv /Users/fujie/code/workspace.toml /Users/fujie/.dotfiles/code-workspace/workspace.toml
mv /Users/fujie/code/ai /Users/fujie/.dotfiles/code-workspace/ai
mv /Users/fujie/code/docs/plans /Users/fujie/.dotfiles/code-workspace/docs/plans
mv /Users/fujie/code/docs/lessons.md /Users/fujie/.dotfiles/code-workspace/docs/lessons.md
mv /Users/fujie/code/docs/archive /Users/fujie/.dotfiles/code-workspace/docs/archive
```

Expected:

```text
```

- [ ] **Step 4: Recreate symlinks into `/Users/fujie/code`**

Run:

```bash
ln -s /Users/fujie/.dotfiles/code-workspace/AGENTS.md /Users/fujie/code/AGENTS.md
ln -s /Users/fujie/.dotfiles/code-workspace/CLAUDE.md /Users/fujie/code/CLAUDE.md
ln -s /Users/fujie/.dotfiles/code-workspace/workspace.md /Users/fujie/code/workspace.md
ln -s /Users/fujie/.dotfiles/code-workspace/workspace.toml /Users/fujie/code/workspace.toml
ln -s /Users/fujie/.dotfiles/code-workspace/ai /Users/fujie/code/ai
ln -s /Users/fujie/.dotfiles/code-workspace/docs/plans /Users/fujie/code/docs/plans
ln -s /Users/fujie/.dotfiles/code-workspace/docs/lessons.md /Users/fujie/code/docs/lessons.md
ln -s /Users/fujie/.dotfiles/code-workspace/docs/archive /Users/fujie/code/docs/archive
```

Expected:

```text
```

- [ ] **Step 5: Verify Codex and Claude entrypoints resolve**

Run:

```bash
test -f /Users/fujie/code/AGENTS.md
test -f /Users/fujie/code/CLAUDE.md
test -f /Users/fujie/code/workspace.md
test -f /Users/fujie/code/workspace.toml
test -d /Users/fujie/code/ai
test -d /Users/fujie/code/docs/plans
readlink /Users/fujie/code/AGENTS.md
readlink /Users/fujie/code/CLAUDE.md
readlink /Users/fujie/code/ai
```

Expected:

```text
/Users/fujie/.dotfiles/code-workspace/AGENTS.md
/Users/fujie/.dotfiles/code-workspace/CLAUDE.md
/Users/fujie/.dotfiles/code-workspace/ai
```

- [ ] **Step 6: Verify workspace checks through symlinks**

Run:

```bash
python3 /Users/fujie/code/ai/checks/check_workspace.py
python3 /Users/fujie/code/ai/tools/sync_agents.py
python3 - <<'PY'
import pathlib, tomllib
for path in pathlib.Path('/Users/fujie/code/.codex/agents').glob('*.toml'):
    tomllib.loads(path.read_text())
print('codex agent toml ok')
PY
```

Expected:

```text
workspace hygiene ok
Synced 7 agents.
codex agent toml ok
```

- [ ] **Step 7: Commit workspace ownership in dotfiles**

Run:

```bash
git -C /Users/fujie/.dotfiles add code-workspace
git -C /Users/fujie/.dotfiles commit -m "chore: manage code workspace config in dotfiles"
```

Expected:

```text
[branch commit] chore: manage code workspace config in dotfiles
```

---

### Task 5: Decide Personal Portfolio Data Policy Before Any Data Commit

**Files:**
- Review: `/Users/fujie/code/playground/stock-price-analyze/portfolio.yaml`
- Review: `/Users/fujie/code/playground/stock-price-analyze/results/2026-05-28/report.md`
- Potentially create: `/Users/fujie/code/playground/stock-price-analyze/portfolio.example.yaml`
- Potentially modify: `/Users/fujie/code/playground/stock-price-analyze/.gitignore`

- [ ] **Step 1: Confirm remaining playground changes**

Run:

```bash
git -C /Users/fujie/code/playground status --short
```

Expected:

```text
 M stock-price-analyze/portfolio.yaml
 M stock-price-analyze/results/2026-05-28/report.md
```

- [ ] **Step 2: Choose one policy for `portfolio.yaml`**

Recommended policy:

```text
Keep real portfolio.yaml local-only, commit portfolio.example.yaml with redacted sample values, and remove portfolio.yaml from the git index.
```

Do not proceed without explicit approval because `portfolio.yaml` contains personal financial positions.

- [ ] **Step 3: If approved, create a redacted example**

Create `/Users/fujie/code/playground/stock-price-analyze/portfolio.example.yaml` with this content:

```yaml
meta:
  currency: JPY
  updated_at: "2026-05-30"
account:
  total_assets: 0
  available_cash: 0
  margin_ratio: 0
holdings:
  - symbol: "7203"
    name: "Sample Corp"
    shares: 100
    average_price: 1000
    market_price: 1000
    unrealized_profit: 0
notes:
  - "Copy this file to portfolio.yaml and replace values with local data."
```

- [ ] **Step 4: If approved, stop tracking real portfolio data**

Run:

```bash
printf '\nportfolio.yaml\nresults/*\n!results/.gitkeep\n' >> /Users/fujie/code/playground/stock-price-analyze/.gitignore
git -C /Users/fujie/code/playground rm --cached stock-price-analyze/portfolio.yaml
git -C /Users/fujie/code/playground add stock-price-analyze/.gitignore stock-price-analyze/portfolio.example.yaml
git -C /Users/fujie/code/playground commit -m "chore: keep portfolio data local"
```

Expected:

```text
[branch commit] chore: keep portfolio data local
```

- [ ] **Step 5: Decide whether historical report should remain tracked**

Recommended policy:

```text
Move analysis reports to runtime/ or keep them ignored under results/, and do not commit future generated reports.
```

If the user approves removing tracked generated reports:

```bash
git -C /Users/fujie/code/playground rm --cached -r stock-price-analyze/results
git -C /Users/fujie/code/playground commit -m "chore: stop tracking generated analysis reports"
```

Expected:

```text
[branch commit] chore: stop tracking generated analysis reports
```

---

### Task 6: Handle Learning DDD As A Separate Repo

**Files:**
- Review: `/Users/fujie/code/learning-ddd/chapter-6.md`

- [ ] **Step 1: Inspect the untracked file**

Run:

```bash
git -C /Users/fujie/code/learning-ddd status --short
git -C /Users/fujie/code/learning-ddd diff -- /dev/null chapter-6.md | sed -n '1,120p'
```

Expected:

```text
?? chapter-6.md
```

- [ ] **Step 2: Commit only if it belongs to the learning-ddd repo**

Run only after confirming it is intentional:

```bash
git -C /Users/fujie/code/learning-ddd add chapter-6.md
git -C /Users/fujie/code/learning-ddd commit -m "docs: add chapter 6 notes"
```

Expected:

```text
[branch commit] docs: add chapter 6 notes
```

---

### Task 7: Final Verification And Review Notes

**Files:**
- Modify: `/Users/fujie/code/docs/plans/2026-05-30-workspace-git-management-next-steps.md`

- [ ] **Step 1: Verify each repo status**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short
git -C /Users/fujie/code/playground status --short
git -C /Users/fujie/code/references/claude-code-best-practice status --short
git -C /Users/fujie/code/learning-ddd status --short
```

Expected after Tasks 2-4:

```text
Only user-approved personal data changes remain uncommitted.
```

- [ ] **Step 2: Verify workspace structure**

Run:

```bash
python3 /Users/fujie/code/ai/checks/check_workspace.py
python3 /Users/fujie/code/ai/tools/sync_agents.py
```

Expected:

```text
workspace hygiene ok
Synced 7 agents.
```

- [ ] **Step 3: Add review notes to this plan**

Append this section after execution:

```markdown
## Review Notes

- Dotfiles portfolio-auth commit:
- Dotfiles workspace ownership commit:
- Playground hygiene commit:
- Personal data policy decision:
- Remaining uncommitted changes:
- Verification commands run:
```

## Self-Review

- Spec coverage: The plan covers post-Claude Code state review, next-step execution, repo ownership, commit sequencing, generated agent verification, and personal portfolio data policy.
- Placeholder scan: The plan does not rely on unspecified implementation steps. User-approval gates are explicit because they involve personal financial data.
- Elegance check: Keeping `/Users/fujie/code` out of git avoids nested repo ambiguity. Moving workspace config to `.dotfiles` aligns with personal environment ownership and keeps project repos independent.
