# Stock Advisor Runtime Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `stock-advisor` runnable from this dotfiles install without failing on missing Python dependencies.

**Architecture:** Keep the current remote `main` architecture: `stock-advisor` is a script-driven skill built around `scripts/run_signal_engine` and `scripts/signal_engine.py`, not the older multi-agent workspace flow. Add a dedicated setup entrypoint under `claude/skills/stock-advisor/scripts/`, make the runner fail with a clear actionable dependency message, update skill docs to call setup before use, and verify with syntax checks plus CLI smoke tests.

**Tech Stack:** Bash, Python venv, pip, pytest, yfinance, pandas, numpy, stockstats, jpholiday.

---

## Root Cause Investigation

- Reproduction command:

```bash
~/.claude/skills/stock-advisor/scripts/run_signal_engine --help
```

- Observed failure:

```text
ModuleNotFoundError: No module named 'pandas'
```

- Current evidence:
  - `~/.claude/skills/stock-advisor/scripts/.venv` does not exist.
  - `run_signal_engine` falls back to system `python3`.
  - System `python3` is `Python 3.14.3`.
  - `portfolio-fetch` CLI starts successfully, so the immediate blocker is isolated to `stock-advisor` runtime dependencies.

- Working pattern in repo:
  - Skill CLIs live under `claude/skills/*/scripts/`.
  - `run_signal_engine` already centralizes Python selection.
  - `requirements.txt` already declares the runtime dependency set.

## Self-Critique Before Implementation

- A one-off local `pip install pandas` would make this machine work temporarily but leave the dotfiles broken for the next install.
- Auto-installing dependencies silently every time `run_signal_engine` starts would make a financial workflow unpredictable and could hide network failures.
- The smallest durable fix is an explicit setup script plus clear runner diagnostics, then a verified local venv.

---

### Task 1: Add Stock Advisor Setup Script

**Files:**
- Create: `claude/skills/stock-advisor/scripts/setup_env`

- [x] **Step 1: Create executable setup script**

Add this file:

```bash
#!/usr/bin/env bash
# setup_env - create stock-advisor Python venv and install runtime dependencies
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN="${MORNING_CHECK_PYTHON:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python not found: $PYTHON_BIN" >&2
  echo "Set MORNING_CHECK_PYTHON to a valid Python executable, or install python3." >&2
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo "OK: stock-advisor environment is ready: $VENV_DIR"
```

- [x] **Step 2: Make script executable**

Run:

```bash
chmod +x claude/skills/stock-advisor/scripts/setup_env
```

Expected: `ls -l claude/skills/stock-advisor/scripts/setup_env` shows executable bits.

### Task 2: Make Runner Diagnose Missing Dependencies

**Files:**
- Modify: `claude/skills/stock-advisor/scripts/run_signal_engine`

- [x] **Step 1: Update runner to prefer local venv and explain missing setup**

Replace the bottom execution block:

```bash
PYTHON="$(find_python)"
exec "$PYTHON" "$SCRIPT_DIR/signal_engine.py" "$@"
```

with:

```bash
PYTHON="$(find_python)"

if ! "$PYTHON" -c "import pandas; import yfinance; import stockstats; import jpholiday" >/dev/null 2>&1
then
  echo "ERROR: stock-advisor Python dependencies are not installed for: $PYTHON" >&2
  echo "Run: $SCRIPT_DIR/setup_env" >&2
  echo "Then retry: $SCRIPT_DIR/run_signal_engine --help" >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/signal_engine.py" "$@"
```

Note: use `python -c` instead of a shell here-doc because sandboxed shells may fail to create the temporary here-doc file.

Expected: without `.venv`, the runner exits with the setup command instead of a Python traceback.

### Task 3: Ignore Runtime Artifacts

**Files:**
- Modify: `.gitignore`

- [x] **Step 1: Add local runtime ignores**

Add these lines if absent:

```gitignore
.env
.cookie
.tokens.json
__pycache__/
*.py[cod]
.venv/
cache/
```

Expected: `.venv`, caches, pycache, and local SBI credentials are not staged by `git add -A`.

### Task 4: Update Skill Documentation

**Files:**
- Modify: `claude/skills/stock-advisor/SKILL.md`

- [x] **Step 1: Add first-run setup section before Step 1**

Insert this section before `### Step 1: データ取得`:

````markdown
### Step 0: 初回セットアップ

`run_signal_engine` が依存関係エラーを出す場合、以下を実行して専用 venv を作成する:

```bash
~/.claude/skills/stock-advisor/scripts/setup_env
```

セットアップ後、以下で CLI が起動することを確認する:

```bash
~/.claude/skills/stock-advisor/scripts/run_signal_engine --help
```
````

Expected: users and agents know the exact recovery command.

### Task 5: Verify Dependency Setup Locally

**Files:**
- Verify: `claude/skills/stock-advisor/scripts/setup_env`
- Verify: `claude/skills/stock-advisor/scripts/run_signal_engine`

- [x] **Step 1: Run setup**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/setup_env
```

Expected:

```text
OK: stock-advisor environment is ready: /Users/fujie/.claude/skills/stock-advisor/scripts/.venv
```

- [x] **Step 2: Verify CLI help**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/run_signal_engine --help
```

Expected: argparse help text is printed and exit code is 0.

- [x] **Step 3: Verify portfolio-fetch still starts**

Run:

```bash
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio --help
```

Expected: argparse help text is printed and exit code is 0.

### Task 6: Run Tests And Smoke Checks

**Files:**
- Verify: `claude/skills/stock-advisor/scripts/*.py`
- Verify: `claude/skills/stock-advisor/scripts/tests/*.py`

- [x] **Step 1: Syntax check core scripts**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python -m py_compile \
  claude/skills/stock-advisor/scripts/signal_engine.py \
  claude/skills/stock-advisor/scripts/data_utils.py \
  claude/skills/stock-advisor/scripts/backtest_engine.py \
  claude/skills/stock-advisor/scripts/trade_advisor.py
```

Expected: exit code 0.

- [x] **Step 2: Install pytest for local verification**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python -m pip install pytest
```

Expected: pytest is installed in the local stock-advisor venv.

- [x] **Step 3: Run unit tests**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python -m pytest \
  claude/skills/stock-advisor/scripts/tests
```

Expected: tests pass.

- [x] **Step 4: Run one ticker smoke test**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/run_signal_engine \
  --ticker 7974.T \
  --output /tmp/stock-advisor-smoke.json
```

Expected: exit code 0 and `/tmp/stock-advisor-smoke.json` contains valid JSON with ticker data for `7974.T`. If Yahoo Finance rate limits or network is unavailable, record that as an environment limitation rather than changing code.

### Task 7: Stage And Review

**Files:**
- Review: `.gitignore`
- Review: `claude/skills/stock-advisor/SKILL.md`
- Review: `claude/skills/stock-advisor/scripts/run_signal_engine`
- Review: `claude/skills/stock-advisor/scripts/setup_env`
- Review: `tasks/todo.md`

- [x] **Step 1: Check ignored local artifacts**

Run:

```bash
git status --ignored --short
```

Expected: `.venv/`, `__pycache__/`, local credentials, and cache directories are ignored.

- [x] **Step 2: Stage safe files only**

Run:

```bash
git add .gitignore \
  claude/skills/stock-advisor/SKILL.md \
  claude/skills/stock-advisor/scripts/run_signal_engine \
  claude/skills/stock-advisor/scripts/setup_env \
  tasks/todo.md
```

Expected: runtime artifacts are not staged.

- [x] **Step 3: Verify staged diff**

Run:

```bash
git diff --cached --name-status
git diff --cached --stat
```

Expected: only the planned files are staged.

## Review

- Implemented `setup_env` to create `scripts/.venv` and install `requirements.txt`.
- Updated `run_signal_engine` to detect missing dependencies and print the exact setup command instead of a Python traceback.
- Updated `.gitignore` so local credentials, venvs, Python caches, and data caches stay out of git.
- Updated `SKILL.md` with first-run setup instructions.
- Verification:
  - `setup_env`: passed.
  - `run_signal_engine --help`: passed.
  - `portfolio-fetch --help`: passed.
  - `py_compile` for core scripts: passed.
  - `pytest claude/skills/stock-advisor/scripts/tests`: 68 passed.
  - `run_signal_engine --ticker 7974.T --output /tmp/stock-advisor-smoke.json`: passed and produced valid JSON.
