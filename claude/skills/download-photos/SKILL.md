---
name: download-photos
description: Download cart photos from photo service sites (8122.jp, fujifilm-fasp.jp).
when_to_use: 「写真をダウンロードして」「カートの写真を取って」「8122」「fujifilm」または /download-photos 実行時
---

# Photo Cart Downloader

Download photos from photo service cart pages using Playwright.

Supported sites: `8122` (8122.jp), `fujifilm-fasp` (fujifilm-fasp.jp).

## Prerequisites

- Environment variables `SITE_EMAIL` and `SITE_PASSWORD` must be set in `.env` in the skill directory.
- Copy `.env.example` to `.env` and fill in credentials if not already done.
- Python venv with dependencies at `$SKILL_DIR/.venv/`.

## Setup

```bash
cd "$SKILL_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

If `.venv` already exists, just activate it:
```bash
source "$SKILL_DIR/.venv/bin/activate"
```

## Commands

### Analyze site structure

Use `--analyze` to inspect a site's cart page and output all image elements as JSON:

```bash
cd "$SKILL_DIR" && source .venv/bin/activate
python download_cart_photos.py --site fujifilm-fasp --analyze
```

This outputs JSON with all `<img>` elements, their attributes, parent hierarchy, and form inputs.
Use the result to fill in the `SITES["fujifilm-fasp"]` definition in `download_cart_photos.py`.

### Download photos

```bash
cd "$SKILL_DIR" && source .venv/bin/activate
python download_cart_photos.py --site 8122 -o ./downloads [-n <count>]
```

Options:
- `--site` - Site key: `8122` (default) or `fujifilm-fasp`
- `-o <dir>` - Output directory (default: `./downloads`)
- `-n <count>` - Max photos to download (default: all)

## Error Handling

- Login failed → check `.env` credentials
- Playwright not installed → run `playwright install chromium`
- Script times out → use `-n` to limit count
