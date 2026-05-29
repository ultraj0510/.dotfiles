# Code Workspace Structure Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the post-migration cleanup of `/Users/fujie/code` so Codex and Claude Code share stable source definitions while runtime state, historical docs, generated files, and real projects have clear boundaries.

**Architecture:** Keep the new `workspace.md`, `ai/`, `runtime/`, and `scratch/` model. Add a lightweight workspace manifest and hygiene checks, move or ignore agent/session state that appeared under source folders, formalize generated agent ownership, and decide repository layout before moving `playground`.

**Tech Stack:** Markdown, Python 3, git, shell verification commands, Codex/Claude agent definitions.

---

## Current Findings After Claude Code Migration

Completed successfully:

- `/Users/fujie/code/workspace.md` exists and `AGENTS.md` / `CLAUDE.md` are now thin entrypoints.
- `/Users/fujie/code/ai/agents/stock-analysis` exists as the shared agent source.
- `/Users/fujie/code/ai/tools/sync_agents.py` generates both `.claude/agents/*.md` and `.codex/agents/*.toml`.
- Generated Codex TOML parses successfully.
- `/Users/fujie/code/runtime` and `/Users/fujie/code/scratch` exist.
- `/Users/fujie/code/docs/plans` and `/Users/fujie/code/docs/lessons.md` exist.

Remaining problems:

- `/Users/fujie/code/projects` and `/Users/fujie/code/references` do not exist, though `workspace.md` and docs refer to them.
- `/Users/fujie/code/playground` remains the real git repo containing operational `stock-price-analyze`; this is still misleading.
- `/Users/fujie/code/claude-code-best-practice` remains at root instead of `references/`.
- `.omc` state exists in multiple places, including `/Users/fujie/code/ai/agents/stock-analysis/.omc`, which pollutes the agent source tree.
- `/Users/fujie/code/docs/superpowers/.DS_Store` exists under docs.
- Historical plans/specs still contain old paths such as `/Users/fujie/code/deepcode/.claude`, `~/.claude/skills/stock-advisor/_workspace`, and `~/code/playground/stock-price-analyze`.
- `/Users/fujie/code/playground` has a dirty worktree:
  - deleted `.DS_Store`
  - modified `stock-price-analyze/.gitignore`
  - modified `stock-price-analyze/portfolio.yaml`
  - modified `stock-price-analyze/results/2026-05-28/report.md`
  - untracked `.omc/`, `stock-price-analyze/.omc/`, `stock-price-analyze/progress.txt`
- `/Users/fujie/code/learning-ddd` has untracked `chapter-6.md`.
- `/Users/fujie/code` itself is not a git repository, so workspace-level changes are currently not versioned unless moved into a managed repo.

## Target Structure

```text
/Users/fujie/code/
  AGENTS.md
  CLAUDE.md
  workspace.md
  workspace.toml

  ai/
    agents/stock-analysis/*.md
    tools/sync_agents.py
    checks/check_workspace.py

  .claude/
    agents/*.md              # generated
    rules/*.md
    settings.local.json

  .codex/
    agents/*.toml            # generated

  projects/
    stock-analysis-workspace/ # future renamed playground repo, after approval
    learning-ddd/             # future move, after approval

  references/
    claude-code-best-practice/ # future move, after approval

  docs/
    plans/
    reviews/
    lessons.md
    archive/

  runtime/
    omc/
    stock-advisor/
    stock-price-analyze-results/

  scratch/
    playground/
```

## Task 1: Add a Workspace Manifest

**Files:**
- Create: `/Users/fujie/code/workspace.toml`
- Modify: `/Users/fujie/code/workspace.md`

- [ ] **Step 1: Create `workspace.toml`**

Create `/Users/fujie/code/workspace.toml`:

```toml
[workspace]
root = "/Users/fujie/code"
source_of_truth = "workspace.md"
default_plan_dir = "docs/plans"
default_lessons_file = "docs/lessons.md"

[tools]
codex_entrypoint = "AGENTS.md"
claude_entrypoint = "CLAUDE.md"
shared_agent_source = "ai/agents/stock-analysis"
sync_agents = "ai/tools/sync_agents.py"

[runtime]
root = "runtime"
omc = "runtime/omc"
stock_advisor_workspace = "runtime/stock-advisor/workspace"
stock_results = "runtime/stock-price-analyze-results"

[projects.current]
stock_price_analyze = "playground/stock-price-analyze"
playground_repo = "playground"
learning_ddd = "learning-ddd"

[projects.proposed]
stock_analysis_workspace = "projects/stock-analysis-workspace"
learning_ddd = "projects/learning-ddd"

[references.current]
claude_code_best_practice = "claude-code-best-practice"

[references.proposed]
claude_code_best_practice = "references/claude-code-best-practice"

[generated]
claude_agents = ".claude/agents"
codex_agents = ".codex/agents"
```

- [ ] **Step 2: Link manifest from `workspace.md`**

Add this section near the top of `/Users/fujie/code/workspace.md`:

```markdown
## Workspace Manifest

Machine-readable workspace paths live in `/Users/fujie/code/workspace.toml`.
When a path changes, update `workspace.toml` first, then update prose docs and generated files.
```

- [ ] **Step 3: Verify manifest exists**

Run:

```bash
python3 - <<'PY'
import tomllib
from pathlib import Path
data = tomllib.loads(Path("/Users/fujie/code/workspace.toml").read_text())
assert data["workspace"]["root"] == "/Users/fujie/code"
assert data["tools"]["shared_agent_source"] == "ai/agents/stock-analysis"
print("workspace manifest ok")
PY
```

Expected:

```text
workspace manifest ok
```

## Task 2: Add a Workspace Hygiene Check

**Files:**
- Create: `/Users/fujie/code/ai/checks/check_workspace.py`

- [ ] **Step 1: Create check directory**

Run:

```bash
mkdir -p /Users/fujie/code/ai/checks
```

- [ ] **Step 2: Create checker**

Create `/Users/fujie/code/ai/checks/check_workspace.py`:

```python
#!/usr/bin/env python3
import sys
import tomllib
from pathlib import Path

ROOT = Path("/Users/fujie/code")
MANIFEST = ROOT / "workspace.toml"

FORBIDDEN_NAMES = {".DS_Store", "__pycache__", ".pytest_cache"}
FORBIDDEN_SOURCE_STATE = {
    ROOT / "ai" / "agents" / "stock-analysis" / ".omc",
}
REQUIRED_PATHS = [
    ROOT / "workspace.md",
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / "ai" / "agents" / "stock-analysis",
    ROOT / "ai" / "tools" / "sync_agents.py",
    ROOT / "docs" / "plans",
    ROOT / "docs" / "lessons.md",
    ROOT / "runtime",
    ROOT / "scratch",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not MANIFEST.exists():
        fail(f"missing {MANIFEST}")

    data = tomllib.loads(MANIFEST.read_text())
    if data["workspace"]["root"] != str(ROOT):
        fail("workspace.root does not match /Users/fujie/code")

    for path in REQUIRED_PATHS:
        if not path.exists():
            fail(f"missing required path: {path}")

    for path in FORBIDDEN_SOURCE_STATE:
        if path.exists():
            fail(f"runtime state under source tree: {path}")

    bad = []
    for path in ROOT.rglob("*"):
        if path.name in FORBIDDEN_NAMES:
            bad.append(path)
    if bad:
        for path in bad:
            print(f"FORBIDDEN: {path}", file=sys.stderr)
        fail("forbidden generated files exist")

    print("workspace hygiene ok")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run checker and capture current failures**

Run:

```bash
python3 /Users/fujie/code/ai/checks/check_workspace.py
```

Expected before cleanup:

```text
FAIL lines for existing .DS_Store, __pycache__, .pytest_cache, or ai/agents/stock-analysis/.omc.
```

Do not weaken the check to pass. Clean the workspace in later tasks.

## Task 3: Clean Runtime State Out of Source Trees

**Files:**
- Move runtime state only
- Modify: `/Users/fujie/code/runtime/README.md`

- [ ] **Step 1: Move source-tree `.omc` state into runtime**

Run:

```bash
mkdir -p /Users/fujie/code/runtime/omc/workspace-root
mkdir -p /Users/fujie/code/runtime/omc/ai-agents-stock-analysis
mkdir -p /Users/fujie/code/runtime/omc/deepcode

if [ -d /Users/fujie/code/.omc ]; then
  mv /Users/fujie/code/.omc /Users/fujie/code/runtime/omc/workspace-root/.omc
fi

if [ -d /Users/fujie/code/ai/agents/stock-analysis/.omc ]; then
  mv /Users/fujie/code/ai/agents/stock-analysis/.omc /Users/fujie/code/runtime/omc/ai-agents-stock-analysis/.omc
fi

if [ -d /Users/fujie/code/deepcode/.omc ]; then
  mv /Users/fujie/code/deepcode/.omc /Users/fujie/code/runtime/omc/deepcode/.omc
fi
```

- [ ] **Step 2: Remove empty `deepcode` if it only held runtime state**

Run:

```bash
find /Users/fujie/code/deepcode -maxdepth 2 -print
```

If output is only `/Users/fujie/code/deepcode`, remove it:

```bash
rmdir /Users/fujie/code/deepcode
```

- [ ] **Step 3: Update runtime README**

Append to `/Users/fujie/code/runtime/README.md`:

```markdown

## OMC State

Historical `.omc` state from workspace-level sessions is stored under:

- `/Users/fujie/code/runtime/omc/workspace-root`
- `/Users/fujie/code/runtime/omc/ai-agents-stock-analysis`
- `/Users/fujie/code/runtime/omc/deepcode`

Do not place `.omc` under `ai/`, `docs/`, or project source directories.
```

## Task 4: Remove Generated Cache Files

**Files:**
- Delete generated files only
- Modify later: ignore files in relevant git repos

- [ ] **Step 1: Remove macOS and Python caches from workspace**

Run:

```bash
find /Users/fujie/code -name .DS_Store -delete
find /Users/fujie/code -name __pycache__ -type d -prune -exec rm -rf {} +
find /Users/fujie/code -name .pytest_cache -type d -prune -exec rm -rf {} +
```

- [ ] **Step 2: Re-run hygiene check**

Run:

```bash
python3 /Users/fujie/code/ai/checks/check_workspace.py
```

Expected:

```text
workspace hygiene ok
```

- [ ] **Step 3: Add ignore rules where repos are dirty**

Inspect:

```bash
git -C /Users/fujie/code/playground status --short
sed -n '1,200p' /Users/fujie/code/playground/.gitignore 2>/dev/null || true
sed -n '1,200p' /Users/fujie/code/playground/stock-price-analyze/.gitignore
```

If `.DS_Store`, `.omc`, `.pytest_cache`, `__pycache__`, and `progress.txt` are not ignored, add them to the relevant `.gitignore` in the repo that owns the files.

## Task 5: Formalize Generated Agent Ownership

**Files:**
- Modify: `/Users/fujie/code/ai/tools/sync_agents.py`
- Create: `/Users/fujie/code/ai/agents/README.md`
- Create: `/Users/fujie/code/.claude/agents/README.md`
- Create: `/Users/fujie/code/.codex/agents/README.md`

- [ ] **Step 1: Add generated headers**

Modify `write_codex_agent()` in `/Users/fujie/code/ai/tools/sync_agents.py` so generated TOML begins with:

```toml
# Generated from /Users/fujie/code/ai/agents/stock-analysis.
# Do not edit directly. Run: python3 /Users/fujie/code/ai/tools/sync_agents.py
```

Modify Claude generation so generated Markdown begins with:

```markdown
<!-- Generated from /Users/fujie/code/ai/agents/stock-analysis. Do not edit directly. -->
```

while preserving the YAML frontmatter after the comment.

- [ ] **Step 2: Create source README**

Create `/Users/fujie/code/ai/agents/README.md`:

```markdown
# Agent Sources

This directory is the source of truth for workspace-local agents shared by Codex and Claude Code.

Edit files under `stock-analysis/`, then run:

```bash
python3 /Users/fujie/code/ai/tools/sync_agents.py
```

Generated files:

- `/Users/fujie/code/.claude/agents/*.md`
- `/Users/fujie/code/.codex/agents/*.toml`
```

- [ ] **Step 3: Create generated READMEs**

Create `/Users/fujie/code/.claude/agents/README.md`:

```markdown
# Generated Claude Agents

These files are generated from `/Users/fujie/code/ai/agents/stock-analysis`.

Do not edit agent definitions here. Edit the source and run:

```bash
python3 /Users/fujie/code/ai/tools/sync_agents.py
```
```

Create `/Users/fujie/code/.codex/agents/README.md`:

```markdown
# Generated Codex Agents

These TOML files are generated from `/Users/fujie/code/ai/agents/stock-analysis`.

Do not edit agent definitions here. Edit the source and run:

```bash
python3 /Users/fujie/code/ai/tools/sync_agents.py
```
```

- [ ] **Step 4: Verify source and generated files are synchronized**

Run:

```bash
python3 /Users/fujie/code/ai/tools/sync_agents.py
diff -rq /Users/fujie/code/ai/agents/stock-analysis /Users/fujie/code/.claude/agents \
  | grep -v README.md || true
python3 - <<'PY'
import tomllib
from pathlib import Path
for p in Path("/Users/fujie/code/.codex/agents").glob("*.toml"):
    tomllib.loads(p.read_text())
print("codex agents parse ok")
PY
```

Expected:

```text
Only expected README/header differences appear, and Codex TOML parses.
```

## Task 6: Decide and Execute Reference Repository Move

**Files:**
- Create directory: `/Users/fujie/code/references`
- Move after checking repo cleanliness: `/Users/fujie/code/claude-code-best-practice`
- Modify: `/Users/fujie/code/workspace.toml`
- Modify: `/Users/fujie/code/workspace.md`

- [ ] **Step 1: Check reference repo cleanliness**

Run:

```bash
git -C /Users/fujie/code/claude-code-best-practice status --short
```

Expected:

```text
No output.
```

- [ ] **Step 2: Move reference repo**

Run:

```bash
mkdir -p /Users/fujie/code/references
mv /Users/fujie/code/claude-code-best-practice /Users/fujie/code/references/claude-code-best-practice
```

- [ ] **Step 3: Update manifest and workspace docs**

In `/Users/fujie/code/workspace.toml`, change:

```toml
[references.current]
claude_code_best_practice = "claude-code-best-practice"
```

to:

```toml
[references.current]
claude_code_best_practice = "references/claude-code-best-practice"
```

In `/Users/fujie/code/workspace.md`, add or update the primary areas row:

```markdown
| `/Users/fujie/code/references/claude-code-best-practice` | External reference material for Claude Code/Codex workflows. |
```

- [ ] **Step 4: Verify moved repo**

Run:

```bash
git -C /Users/fujie/code/references/claude-code-best-practice status --short
test ! -d /Users/fujie/code/claude-code-best-practice && echo "old reference path removed"
```

Expected:

```text
old reference path removed
```

## Task 7: Decide Project Repository Layout

**Files:**
- Modify: `/Users/fujie/code/docs/plans/stock-price-analyze-repo-move.md`
- Do not move code in this task unless explicitly approved after reading the decision.

- [ ] **Step 1: Update decision with current evidence**

Append this section to `/Users/fujie/code/docs/plans/stock-price-analyze-repo-move.md`:

```markdown

## 2026-05-30 Current Evidence

- `/Users/fujie/code/playground` is the actual git repo.
- `/Users/fujie/code/playground/stock-price-analyze` is operational source code.
- `/Users/fujie/code/playground` currently has dirty state:
  - `.DS_Store` deletion
  - `stock-price-analyze/.gitignore` modified
  - `stock-price-analyze/portfolio.yaml` modified
  - `stock-price-analyze/results/2026-05-28/report.md` modified
  - `.omc/`, `stock-price-analyze/.omc/`, `stock-price-analyze/progress.txt` untracked

## Refined Recommendation

Do not split `stock-price-analyze` yet.

First clean generated state and personal data handling inside the existing `playground` repo. Then rename the whole repo directory from `/Users/fujie/code/playground` to `/Users/fujie/code/projects/stock-analysis-workspace` in a dedicated move step.
```

- [ ] **Step 2: Create projects directory only**

Run:

```bash
mkdir -p /Users/fujie/code/projects
```

- [ ] **Step 3: Verify no physical project move occurred**

Run:

```bash
test -d /Users/fujie/code/playground/stock-price-analyze && echo "stock project still in current repo"
```

Expected:

```text
stock project still in current repo
```

## Task 8: Clean Playground Repo State Before Any Move

**Files:**
- Modify: `/Users/fujie/code/playground/.gitignore` or `/Users/fujie/code/playground/stock-price-analyze/.gitignore`
- Do not modify: `/Users/fujie/code/playground/stock-price-analyze/portfolio.yaml` unless the user explicitly approves

- [ ] **Step 1: Inspect dirty files**

Run:

```bash
git -C /Users/fujie/code/playground status --short
git -C /Users/fujie/code/playground diff -- stock-price-analyze/.gitignore
git -C /Users/fujie/code/playground diff -- stock-price-analyze/results/2026-05-28/report.md
```

- [ ] **Step 2: Add ignore rules for generated state**

If not already present, add to `/Users/fujie/code/playground/.gitignore`:

```gitignore
.DS_Store
.omc/
**/.omc/
**/.pytest_cache/
**/__pycache__/
**/progress.txt
```

- [ ] **Step 3: Decide personal-data files**

Before committing, ask whether these files should remain tracked:

```text
stock-price-analyze/portfolio.yaml
stock-price-analyze/results/2026-05-28/report.md
stock-price-analyze/results/2026-05-28/portfolio.txt
stock-price-analyze/results/2026-05-28/signals.json
stock-price-analyze/results/2026-05-28/portfolio_analytics.json
```

Recommended policy:

```text
Keep source code and small anonymized fixtures in git.
Move daily personal analysis output to /Users/fujie/code/runtime/stock-price-analyze-results.
Keep real portfolio.yaml out of git; commit portfolio.example.yaml instead.
```

- [ ] **Step 4: Verify status after cleanup**

Run:

```bash
git -C /Users/fujie/code/playground status --short
```

Expected:

```text
Only intentional source/config changes remain.
```

## Task 9: Archive Historical Docs Without Rewriting Them

**Files:**
- Create: `/Users/fujie/code/docs/archive/README.md`
- Move after approval: old superpowers plans/specs into `/Users/fujie/code/docs/archive/superpowers-history`

- [ ] **Step 1: Create archive README**

Run:

```bash
mkdir -p /Users/fujie/code/docs/archive
```

Create `/Users/fujie/code/docs/archive/README.md`:

```markdown
# Archive

Historical plans and specs are preserved here for context.

Archived files may contain old paths such as `/Users/fujie/code/deepcode` or `~/.claude/skills/stock-advisor`.
Do not update archived files in place unless they are being revived as active plans.
```

- [ ] **Step 2: Add active-vs-archive policy**

Append to `/Users/fujie/code/docs/plans/README.md`:

```markdown

## Active vs Archived Plans

Active plans should use current paths from `/Users/fujie/code/workspace.toml`.

Historical plans with old paths should be moved to `/Users/fujie/code/docs/archive` instead of being edited in place.
```

- [ ] **Step 3: Do not bulk edit old plans**

Run:

```bash
rg -n "/Users/fujie/code/deepcode|~/.claude/skills/stock-advisor|~/code/playground/stock-price-analyze" /Users/fujie/code/docs
```

Expected:

```text
Old references are allowed only under docs/archive or clearly historical docs.
```

## Task 10: Version the Workspace-Level Configuration

**Files:**
- New git repo candidate: `/Users/fujie/code`
- Alternative: move workspace config into `/Users/fujie/.dotfiles`

- [ ] **Step 1: Choose ownership**

Choose one:

```text
Option A: Initialize /Users/fujie/code as a git repo for workspace config only.
Option B: Move /Users/fujie/code/{AGENTS.md,CLAUDE.md,workspace.md,workspace.toml,ai,docs/plans,docs/lessons.md} into /Users/fujie/.dotfiles/code-workspace and symlink back.
```

Recommendation:

```text
Option B. Workspace config behaves like personal environment configuration and should live with dotfiles, while project repos remain independent.
```

- [ ] **Step 2: If choosing dotfiles, write a dedicated follow-up plan**

Create:

```text
/Users/fujie/code/docs/plans/2026-05-30-code-workspace-dotfiles-ownership.md
```

This follow-up plan must list every symlink and rollback step before moving files.

## Task 11: Verification

**Files:**
- Verify only

- [ ] **Step 1: Run workspace hygiene**

```bash
python3 /Users/fujie/code/ai/checks/check_workspace.py
```

Expected:

```text
workspace hygiene ok
```

- [ ] **Step 2: Run agent sync and parse verification**

```bash
python3 /Users/fujie/code/ai/tools/sync_agents.py
python3 - <<'PY'
import tomllib
from pathlib import Path
for p in Path("/Users/fujie/code/.codex/agents").glob("*.toml"):
    tomllib.loads(p.read_text())
print("codex agents parse ok")
PY
```

Expected:

```text
codex agents parse ok
```

- [ ] **Step 3: Check source/generated drift**

```bash
diff -rq /Users/fujie/code/ai/agents/stock-analysis /Users/fujie/code/.claude/agents \
  | grep -v README.md || true
```

Expected:

```text
Only expected generated-header differences appear.
```

- [ ] **Step 4: Check git repos**

```bash
git -C /Users/fujie/code/playground status --short
git -C /Users/fujie/code/learning-ddd status --short
git -C /Users/fujie/code/references/claude-code-best-practice status --short
```

Expected:

```text
Only known intentional changes remain.
```

## Self-Review

- Spec coverage: This plan addresses the actual post-migration state, including new `ai/`, `runtime/`, and `scratch` directories, remaining old root directories, runtime state leakage, generated agent ownership, dirty git repos, historical docs, and workspace config versioning.
- Placeholder scan: No unspecified implementation placeholder is required; every task has concrete files, commands, and expected outcomes.
- Type consistency: `workspace.toml`, `workspace.md`, `sync_agents.py`, generated agent definitions, and runtime paths use consistent names throughout.
