# Dotfiles Tasks Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/Users/fujie/.dotfiles/tasks/` をgit管理対象から廃止し、今後の計画・教訓の保存先を `/Users/fujie/code/docs/` に一本化する。

**Architecture:** `tasks/` は一時作業状態として扱い、tracked file を削除して `.gitignore` で再混入を防ぐ。永続化が必要な計画は `/Users/fujie/.dotfiles/code-workspace/docs/plans/`、教訓は `/Users/fujie/.dotfiles/code-workspace/docs/lessons.md` に集約し、Claude向けの古い指示を更新する。

**Tech Stack:** git, Markdown, Codex/Claude workspace config, dotfiles

---

## Current State

- `/Users/fujie/.dotfiles/tasks/todo.md` だけが git tracked。
- `/Users/fujie/.dotfiles/tasks/todo.md` は完了済みの `Stock Advisor Runtime Fix Implementation Plan`。
- `/Users/fujie/.dotfiles/claude/CLAUDE.md` が `tasks/todo.md` と `tasks/lessons.md` を現在の保存先として指示している。
- `/Users/fujie/.dotfiles/code-workspace/workspace.toml` には既存の未コミット差分があるため、この計画では同ファイルを編集しない。
- `/Users/fujie/code/workspace.toml` は `/Users/fujie/.dotfiles/code-workspace/workspace.toml` へのsymlink。

## Target Policy

- `tasks/` はgit管理しない。
- 新規計画は `/Users/fujie/code/docs/plans/` に保存する。
- セッション横断で残す教訓は `/Users/fujie/code/docs/lessons.md` に保存する。
- 完了済みで残す価値がある古い計画だけ `/Users/fujie/code/docs/archive/` に移す。
- 作業中の一時メモが必要な場合は `runtime/` または `scratch/` を使う。

## File Responsibility Map

- Modify: `/Users/fujie/.dotfiles/.gitignore`
  - `tasks/` をignoreし、今後の再追加を防ぐ。
- Modify: `/Users/fujie/.dotfiles/claude/CLAUDE.md`
  - `tasks/todo.md` / `tasks/lessons.md` 参照を廃止し、`/Users/fujie/code/docs/plans/` / `/Users/fujie/code/docs/lessons.md` に差し替える。
- Move or remove from git: `/Users/fujie/.dotfiles/tasks/todo.md`
  - 履歴として残すなら archive へ移動、不要なら tracking から削除。
- Potentially create: `/Users/fujie/.dotfiles/code-workspace/docs/archive/2026-05-30-stock-advisor-runtime-fix-plan.md`
  - `tasks/todo.md` の内容を保持する場合だけ作成する。

---

### Task 1: Confirm Scope And Preserve Existing Unrelated Changes

**Files:**
- Read: `/Users/fujie/.dotfiles`
- Read: `/Users/fujie/.dotfiles/code-workspace/workspace.toml`
- Read: `/Users/fujie/.dotfiles/tasks/todo.md`

- [ ] **Step 1: Confirm tracked files under `tasks/`**

Run:

```bash
git -C /Users/fujie/.dotfiles ls-files tasks
git -C /Users/fujie/.dotfiles status --short -- tasks
```

Expected:

```text
tasks/todo.md
```

The second command should print no lines. If it prints a modified `tasks/todo.md`, inspect it before removing tracking.

- [ ] **Step 2: Confirm unrelated dirty state**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short
git -C /Users/fujie/.dotfiles diff -- code-workspace/workspace.toml
```

Expected:

```text
 M code-workspace/workspace.toml
```

The `workspace.toml` diff is an existing structural cleanup. Do not stage it in this retirement commit.

- [ ] **Step 3: Confirm current references to `tasks/`**

Run:

```bash
rg -n "tasks/todo|tasks/lessons|Task Management" /Users/fujie/.dotfiles/claude/CLAUDE.md /Users/fujie/.dotfiles/code-workspace /Users/fujie/.dotfiles/tasks
```

Expected includes:

```text
/Users/fujie/.dotfiles/claude/CLAUDE.md:110:- After ANY correction from the user: update `tasks/lessons.md` with the pattern
/Users/fujie/.dotfiles/claude/CLAUDE.md:138:## Task Management
/Users/fujie/.dotfiles/claude/CLAUDE.md:140:1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
```

---

### Task 2: Update Claude Instructions Away From `tasks/`

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/CLAUDE.md`

- [ ] **Step 1: Replace the Self-Improvement Loop target**

In `/Users/fujie/.dotfiles/claude/CLAUDE.md`, replace:

```markdown
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
```

with:

```markdown
- After ANY correction from the user: update `/Users/fujie/code/docs/lessons.md` with the pattern
```

- [ ] **Step 2: Replace the Task Management section**

In `/Users/fujie/.dotfiles/claude/CLAUDE.md`, replace the whole section:

```markdown
## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections
```

with:

```markdown
## Task Management

1. **Plan First**: Write durable plans to `/Users/fujie/code/docs/plans/` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Update the active plan file as work progresses
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review notes to the active plan file
6. **Capture Lessons**: Update `/Users/fujie/code/docs/lessons.md` after corrections
```

- [ ] **Step 3: Verify the old targets are gone from active Claude instructions**

Run:

```bash
rg -n "tasks/todo|tasks/lessons" /Users/fujie/.dotfiles/claude/CLAUDE.md
```

Expected:

```text
```

---

### Task 3: Archive Or Remove Existing `tasks/todo.md`

**Files:**
- Remove from git: `/Users/fujie/.dotfiles/tasks/todo.md`
- Potentially create: `/Users/fujie/.dotfiles/code-workspace/docs/archive/2026-05-30-stock-advisor-runtime-fix-plan.md`

- [ ] **Step 1: Decide whether to keep the historical plan**

Recommended decision:

```text
Archive the existing completed plan once, then remove tasks/todo.md from git.
```

Reason: the current file documents the stock-advisor runtime fix and may help future diagnosis, but the `tasks/` location should not remain active.

- [ ] **Step 2: If keeping history, move the file into archive**

Run:

```bash
mv /Users/fujie/.dotfiles/tasks/todo.md /Users/fujie/.dotfiles/code-workspace/docs/archive/2026-05-30-stock-advisor-runtime-fix-plan.md
```

Expected:

```text
```

- [ ] **Step 3: If not keeping history, remove the tracked file**

Run this instead of Step 2 if the historical plan is not needed:

```bash
git -C /Users/fujie/.dotfiles rm tasks/todo.md
```

Expected:

```text
rm 'tasks/todo.md'
```

- [ ] **Step 4: Remove empty local `tasks/` directory if Step 2 was used**

Run only after Step 2:

```bash
rmdir /Users/fujie/.dotfiles/tasks
```

Expected:

```text
```

If `rmdir` fails because another file exists under `tasks/`, run:

```bash
find /Users/fujie/.dotfiles/tasks -maxdepth 2 -type f -print
```

Expected:

```text
```

Stop and inspect any printed file before deleting the directory.

---

### Task 4: Prevent `tasks/` From Reappearing In Git

**Files:**
- Modify: `/Users/fujie/.dotfiles/.gitignore`

- [ ] **Step 1: Add `tasks/` to dotfiles ignore rules**

Append this line to `/Users/fujie/.dotfiles/.gitignore` if absent:

```gitignore
tasks/
```

- [ ] **Step 2: Verify `tasks/` is ignored**

Run:

```bash
mkdir -p /Users/fujie/.dotfiles/tasks
printf 'local scratch\n' > /Users/fujie/.dotfiles/tasks/check-ignore.md
git -C /Users/fujie/.dotfiles check-ignore -v tasks/check-ignore.md
rm /Users/fujie/.dotfiles/tasks/check-ignore.md
rmdir /Users/fujie/.dotfiles/tasks
```

Expected:

```text
.gitignore:<line>:tasks/	tasks/check-ignore.md
```

---

### Task 5: Verify Active Workspace Paths Still Work

**Files:**
- Verify: `/Users/fujie/code/docs/plans`
- Verify: `/Users/fujie/code/docs/lessons.md`
- Verify: `/Users/fujie/code/ai/checks/check_workspace.py`

- [ ] **Step 1: Verify symlinked workspace docs exist**

Run:

```bash
test -d /Users/fujie/code/docs/plans
test -f /Users/fujie/code/docs/lessons.md
test -d /Users/fujie/code/docs/archive
readlink /Users/fujie/code/docs/plans
readlink /Users/fujie/code/docs/lessons.md
readlink /Users/fujie/code/docs/archive
```

Expected:

```text
/Users/fujie/.dotfiles/code-workspace/docs/plans
/Users/fujie/.dotfiles/code-workspace/docs/lessons.md
/Users/fujie/.dotfiles/code-workspace/docs/archive
```

- [ ] **Step 2: Run workspace hygiene check**

Run:

```bash
python3 /Users/fujie/code/ai/checks/check_workspace.py
```

Expected:

```text
workspace hygiene ok
```

- [ ] **Step 3: Confirm no active references point to `tasks/`**

Run:

```bash
rg -n "tasks/todo|tasks/lessons|/Users/fujie/.dotfiles/tasks" /Users/fujie/.dotfiles/claude/CLAUDE.md /Users/fujie/.dotfiles/code-workspace
```

Expected:

```text
```

Historical archive files may still mention `tasks/todo.md`; that is acceptable if the match is under `/Users/fujie/.dotfiles/code-workspace/docs/archive/`.

---

### Task 6: Commit The Retirement Separately

**Files:**
- Stage: `/Users/fujie/.dotfiles/.gitignore`
- Stage: `/Users/fujie/.dotfiles/claude/CLAUDE.md`
- Stage removal: `/Users/fujie/.dotfiles/tasks/todo.md`
- Stage if archived: `/Users/fujie/.dotfiles/code-workspace/docs/archive/2026-05-30-stock-advisor-runtime-fix-plan.md`
- Do not stage: `/Users/fujie/.dotfiles/code-workspace/workspace.toml`

- [ ] **Step 1: Review staged and unstaged scope**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short
git -C /Users/fujie/.dotfiles diff -- .gitignore claude/CLAUDE.md
git -C /Users/fujie/.dotfiles diff --cached --name-only
```

Expected staged files after `git add` in the next step:

```text
.gitignore
claude/CLAUDE.md
code-workspace/docs/archive/2026-05-30-stock-advisor-runtime-fix-plan.md
tasks/todo.md
```

`code-workspace/workspace.toml` must remain unstaged if it is still modified.

- [ ] **Step 2: Stage only the retirement change**

Run:

```bash
git -C /Users/fujie/.dotfiles add .gitignore claude/CLAUDE.md
git -C /Users/fujie/.dotfiles add code-workspace/docs/archive/2026-05-30-stock-advisor-runtime-fix-plan.md 2>/dev/null || true
git -C /Users/fujie/.dotfiles add -u tasks
```

Expected:

```text
```

- [ ] **Step 3: Confirm `workspace.toml` is not staged**

Run:

```bash
git -C /Users/fujie/.dotfiles diff --cached --name-only
git -C /Users/fujie/.dotfiles diff --name-only
```

Expected:

```text
.gitignore
claude/CLAUDE.md
code-workspace/docs/archive/2026-05-30-stock-advisor-runtime-fix-plan.md
tasks/todo.md
code-workspace/workspace.toml
```

Interpretation: the first command should list only the retirement files. The second command may list `code-workspace/workspace.toml` as an existing unstaged change.

- [ ] **Step 4: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles commit -m "chore: retire tracked task scratch files"
```

Expected:

```text
[branch commit] chore: retire tracked task scratch files
```

---

### Task 7: Final Post-Commit Checks

**Files:**
- Verify: `/Users/fujie/.dotfiles`
- Verify: `/Users/fujie/code`

- [ ] **Step 1: Confirm `tasks/` is no longer tracked**

Run:

```bash
git -C /Users/fujie/.dotfiles ls-files tasks
```

Expected:

```text
```

- [ ] **Step 2: Confirm status contains only unrelated prior changes**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short
```

Expected:

```text
 M code-workspace/workspace.toml
```

If `workspace.toml` has already been committed separately, expected output is empty.

- [ ] **Step 3: Confirm GitHub-facing tracked files no longer include `tasks/`**

Run:

```bash
git -C /Users/fujie/.dotfiles ls-tree -r --name-only HEAD | rg '^tasks/' || true
```

Expected:

```text
```

## Self-Review

- Spec coverage: The plan removes `tasks/` from git, updates the instructions that recreate it, preserves existing unrelated `workspace.toml` changes, and adds verification commands.
- Placeholder scan: Every step includes exact paths, commands, and expected output.
- Elegance check: The plan avoids introducing a new task system and reuses the already-established `/Users/fujie/code/docs/` workspace structure.
