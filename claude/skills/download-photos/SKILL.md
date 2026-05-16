---
name: download-8122
description: Download cart photos from 8122.jp. Use when the user wants to download photos from their 8122.jp cart.
---

# 8122.jp Cart Photo Downloader

Download photos from the 8122.jp cart using the bundled Python script.

## Prerequisites

- Environment variables `SITE_EMAIL` and `SITE_PASSWORD` must be set in a `.env` file in the plugin root directory.
- Copy `.env.example` to `.env` and fill in credentials if not already done.

## Execution Steps

When invoked, follow these steps in order:

### 1. Check Environment

Verify that `.env` exists in the plugin root directory (`${CLAUDE_PLUGIN_ROOT}` or the directory containing this skill). If not, tell the user to create it from `.env.example`.

### 2. Setup Python Environment

If `.venv` does not exist or `requirements.txt` has been modified, run:

```bash
cd "$CLAUDE_PLUGIN_ROOT"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

If `.venv` already exists, just activate it:

```bash
source "$CLAUDE_PLUGIN_ROOT/.venv/bin/activate"
```

### 3. Parse Arguments

The user may specify:
- Output directory: `-o <dir>` or `--output <dir>` (default: `./downloads`)
- Photo limit: `-n <count>` or `--limit <count>` (default: all)

Extract these from the user's message. If not specified, use defaults.

### 4. Run Download

Execute the download script:

```bash
cd "$CLAUDE_PLUGIN_ROOT"
source .venv/bin/activate
python download_cart_photos.py [-o <output_dir>] [-n <count>]
```

### 5. Report Results

After completion, show the user:
- Number of photos downloaded successfully
- Number of failures (if any)
- Output directory location
- Total size of downloaded files

If there were failures, list the failed URLs.

## Error Handling

- If login fails, check that credentials in `.env` are correct.
- If Playwright is not installed, run `playwright install chromium`.
- If the script times out, suggest running with `-n` to test with fewer photos first.
