# stock-price-analyze repo move decision

## Current

- Current path: `/Users/fujie/code/playground/stock-price-analyze`
- Containing git repo: `/Users/fujie/code/playground`

## Options

### Option A: Keep inside playground repo and rename later

Pros:
- No immediate git history disruption.
- Lowest risk.

Cons:
- The path continues to imply temporary status.

### Option B: Move entire playground repo to `/Users/fujie/code/projects/stock-analysis-workspace`

Pros:
- Preserves git history.
- Removes misleading `playground` name.

Cons:
- Existing scripts and docs need path updates.

### Option C: Split `stock-price-analyze` into its own repo

Pros:
- Clean project boundary.
- Easier CI and dependency management.

Cons:
- Requires history split or fresh repo.
- More migration work.

## Recommendation

Start with Option B unless there is a strong reason to split history now.

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
