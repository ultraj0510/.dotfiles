#!/usr/bin/env python3
"""Download cart photo images from photo service sites."""

import argparse
import json
import os
import sys
import time
import logging
from pathlib import Path
from urllib.parse import urlparse, unquote

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2

# Site definitions
SITES = {
    "8122": {
        "name": "8122.jp",
        "login_url": "https://8122.jp",
        "cart_url": "https://8122.jp/cart",
        "login_check": "action_user_home",
        "photo_selector": ".p-cart-item_photo_edge img.u-absolute",
        "email_selector": 'textbox[name="メールアドレス"]',
        "password_selector": 'textbox[name="パスワード"]',
        "login_button": 'button[name="ログイン"]',
        "filename_pattern": "{idx:04d}_{name}",
    },
    "fujifilm-fasp": {
        "name": "fujifilm-fasp.jp",
        "login_url": "https://fujifilm-fasp.jp/school/pc/ja/",
        "cart_url": "https://fujifilm-fasp.jp/app/pc/cart",
        "login_check": "/app/pc/mypage",
        "photo_selector": None,  # Nuxt.js SPA - determined dynamically
        "email_selector": 'input[name="login-id"]',
        "password_selector": 'input[name="password"]',
        "login_button": 'a.btn.size--m:has-text("ログイン")',
        "filename_pattern": "{idx:04d}_{name}",
    },
}


def login_8122(page: Page, email: str, password: str) -> None:
    site = SITES["8122"]
    log.info(f"Logging in to {site['name']}...")
    page.goto(site["login_url"], wait_until="networkidle")
    page.get_by_role("textbox", name="メールアドレス").fill(email)
    page.get_by_role("textbox", name="パスワード").fill(password)
    page.get_by_role("button", name="ログイン").click()
    page.wait_for_load_state("networkidle")
    if "action_user_home" not in page.url:
        log.error(f"Login to {site['name']} failed. Check credentials.")
        sys.exit(1)
    log.info("Login successful.")


def login_fujifilm_fasp(page: Page, email: str, password: str) -> None:
    """Log in to fujifilm-fasp.jp. Login uses JavaScript Login() function, not form submit."""
    site = SITES["fujifilm-fasp"]
    log.info(f"Logging in to {site['name']}...")

    page.goto(site["login_url"], wait_until="networkidle")

    # If already logged in, the page will redirect to mypage
    if site["login_check"] in page.url:
        log.info("Already logged in.")
        return

    # Fill credentials and call Login() JS function (clicking the <a> doesn't work in headless)
    page.locator(site["email_selector"]).fill(email)
    page.locator(site["password_selector"]).fill(password)
    page.evaluate("Login('#login_area')")
    page.wait_for_url(f"**{site['login_check']}**", timeout=15000)
    log.info("Login successful.")


def navigate_to_cart(page: Page, site_key: str) -> None:
    site = SITES[site_key]
    log.info(f"Navigating to cart: {site['cart_url']}")
    page.goto(site["cart_url"], wait_until="networkidle")
    log.info(f"Cart page loaded: {page.url}")


def analyze_page(page: Page, site_key: str) -> dict:
    """Extract all image-related elements from the cart page for analysis."""
    site = SITES[site_key]
    log.info(f"Analyzing page: {page.url}")

    result = {
        "site_key": site_key,
        "site_name": site["name"],
        "url": page.url,
        "title": page.title(),
        "images": [],
        "forms": [],
    }

    # Extract all img elements with their attributes and parent context
    imgs = page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('img').forEach((img, idx) => {
            const info = {
                index: idx,
                src: img.src || null,
                alt: img.alt || null,
                class: img.className || null,
                id: img.id || null,
                dataset: {},
                tag: img.tagName,
                // Get parent element info (up to 3 levels)
                parents: []
            };
            // Copy dataset
            if (img.dataset) {
                for (const [k, v] of Object.entries(img.dataset)) {
                    info.dataset[k] = v;
                }
            }
            // Get parent hierarchy
            let el = img.parentElement;
            for (let i = 0; i < 3 && el; i++) {
                const parentInfo = {
                    tag: el.tagName,
                    class: el.className || null,
                    id: el.id || null,
                };
                info.parents.push(parentInfo);
                el = el.parentElement;
            }
            results.push(info);
        });
        return results;
    }""")

    result["images"] = imgs

    # Extract form/input info
    forms = page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('form').forEach((form, idx) => {
            const info = {
                index: idx,
                action: form.action || null,
                method: form.method || null,
                class: form.className || null,
                id: form.id || null,
                inputs: []
            };
            form.querySelectorAll('input, button').forEach(el => {
                info.inputs.push({
                    tag: el.tagName,
                    type: el.type || null,
                    name: el.name || null,
                    id: el.id || null,
                    class: el.className || null,
                    placeholder: el.placeholder || null,
                    value: el.value ? el.value.substring(0, 50) : null, // Truncate long values
                });
            });
            results.push(info);
        });
        return results;
    }""")

    result["forms"] = forms

    # Also try to extract images with lazy-load data-src patterns
    lazy_imgs = page.evaluate("""() => {
        const candidates = [];
        document.querySelectorAll('[data-src], [data-original], [data-lazy]').forEach(el => {
            candidates.push({
                tag: el.tagName,
                class: el.className || null,
                id: el.id || null,
                data_src: el.dataset?.src || null,
                src: el.src || null,
            });
        });
        return candidates;
    }""")

    result["lazy_loaded"] = lazy_imgs

    return result


def get_photo_urls_8122(page: Page) -> list[str]:
    urls = page.evaluate("""() => {
        const imgs = document.querySelectorAll('.p-cart-item_photo_edge img.u-absolute');
        return Array.from(imgs).map(img => {
            if (img.src && img.src.includes('cdn.image.8122.jp')) return img.src;
            if (img.dataset.src && img.dataset.src.includes('cdn.image.8122.jp')) return img.dataset.src;
            return null;
        }).filter(Boolean);
    }""")
    log.info(f"Found {len(urls)} photo URLs in cart")
    return urls


def get_photo_urls_fujifilm_fasp(page: Page) -> list[str]:
    """Extract photo data URLs from fujifilm-fasp cart via blob URL conversion.

    Images are loaded as blob: URLs by the Nuxt.js SPA.
    We convert them to data: URLs in the browser context.
    """
    photos = page.evaluate("""async () => {
        const seen = new Set();
        const results = [];
        const imgs = document.querySelectorAll('img');

        for (const img of imgs) {
            const src = img.src || '';
            if (!src.startsWith('blob:')) continue;
            if (seen.has(src)) continue;
            seen.add(src);

            // Only target cart item thumbnails, skip icons/logos
            const inCartItem = img.closest('[class*="item"]') || img.closest('[class*="cart"]');
            if (!inCartItem) continue;

            try {
                const response = await fetch(src);
                const blob = await response.blob();
                // Skip tiny images (icons)
                if (blob.size < 1024) continue;

                const dataUrl = await new Promise((resolve) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.readAsDataURL(blob);
                });
                results.push(dataUrl);
            } catch (e) {
                // Blob URL may have been revoked; skip
            }
        }
        return results;
    }""")

    log.info(f"Found {len(photos)} photos via blob URL conversion")
    return photos


def get_photo_urls_generic(page: Page) -> list[str]:
    """Extract photo URLs from cart page using generic heuristics."""
    urls = page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('img').forEach(img => {
            const src = img.src || img.dataset?.src || img.dataset?.original || '';
            // Heuristic: photo URLs often contain cdn, image, photo, or specific domains
            if (src && (src.includes('cdn') || src.includes('image') || src.includes('photo') || src.includes('img') || src.includes('fujifilm'))) {
                results.push(src);
            }
        });
        return results;
    }""")
    if not urls:
        # Fallback: grab all img srcs
        urls = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('img')).map(img => img.src || img.dataset?.src).filter(Boolean);
        }""")
    log.info(f"Found {len(urls)} photo URLs (generic extraction)")
    return urls


def download_image(page: Page, url: str, save_path: Path) -> bool:
    if save_path.exists():
        log.info(f"Skipping (already exists): {save_path.name}")
        return True

    # Handle data: URLs (blob conversion from SPA)
    if url.startswith("data:"):
        try:
            import base64
            header, encoded = url.split(",", 1)
            data = base64.b64decode(encoded)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(data)
            log.info(f"Downloaded: {save_path.name} ({len(data)} bytes)")
            return True
        except Exception as e:
            log.error(f"Failed to save data URL: {e}")
            return False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = page.request.get(url, timeout=30000)
            if response.status == 200:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(response.body())
                log.info(f"Downloaded: {save_path.name} ({len(response.body())} bytes)")
                return True
            else:
                log.warning(f"HTTP {response.status} for {url} (attempt {attempt})")
        except Exception as e:
            log.warning(f"Download error (attempt {attempt}): {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    log.error(f"Failed to download after {MAX_RETRIES} attempts: {url}")
    return False


def get_filename_from_url(url: str, index: int) -> str:
    if url.startswith("data:"):
        mime = url.split(";")[0].replace("data:", "")
        ext = mime.split("/")[-1] if "/" in mime else "jpg"
        if ext == "jpeg":
            ext = "jpg"
        return f"photo_{index:04d}.{ext}"

    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    if name and "." in name:
        return f"{index:04d}_{name}"
    return f"photo_{index:04d}.jpg"


def load_cookies_from_file(path: str) -> list[dict]:
    """Load cookies from a JSON file (Playwright format)."""
    with open(path) as f:
        cookies = json.load(f)
    # Normalize: Playwright expects sameSite as string enum, not None
    valid_same_site = {"Strict", "Lax", "None"}
    for c in cookies:
        if c.get("sameSite") not in valid_same_site:
            c.pop("sameSite", None)
        # Playwright doesn't accept hostOnly; remove it
        c.pop("hostOnly", None)
        c.pop("storeId", None)
        c.pop("session", None)
    log.info(f"Loaded {len(cookies)} cookies from {path}")
    return cookies


def create_context_with_auth(browser, site_key: str, email: str | None, password: str | None,
                             cookies_file: str | None):
    """Handle authentication: cookies first, then login fallback. Returns (context, page)."""
    if cookies_file:
        cookies = load_cookies_from_file(cookies_file)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()
        log.info("Using cookie-based authentication")
        return context, page

    context = browser.new_context()
    page = context.new_page()

    if site_key == "8122":
        login_8122(page, email, password)
    elif site_key == "fujifilm-fasp":
        login_fujifilm_fasp(page, email, password)

    return context, page


def run_analyze(site_key: str, email: str | None = None, password: str | None = None,
                cookies_file: str | None = None) -> dict:
    """Run site analysis mode."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context, page = create_context_with_auth(
                browser, site_key, email, password, cookies_file)
            navigate_to_cart(page, site_key)
            result = analyze_page(page, site_key)
        finally:
            browser.close()

    return result


def run_download(site_key: str, email: str | None, password: str | None,
                 download_dir: Path, limit: int | None = None,
                 cookies_file: str | None = None) -> dict:
    stats = {"success": 0, "failed": 0, "skipped": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = None
        context = None

        try:
            context, page = create_context_with_auth(
                browser, site_key, email, password, cookies_file)
            navigate_to_cart(page, site_key)

            if site_key == "8122":
                urls = get_photo_urls_8122(page)
            elif site_key == "fujifilm-fasp":
                urls = get_photo_urls_fujifilm_fasp(page)
            else:
                urls = get_photo_urls_generic(page)

            if not urls:
                log.warning("No photos found in cart")
                return stats

            total = len(urls) if limit is None else min(limit, len(urls))
            log.info(f"Processing {total} of {len(urls)} photos...")

            for i in range(total):
                log.info(f"[{i+1}/{total}] Processing photo {i+1}...")
                filename = get_filename_from_url(urls[i], i)
                save_path = download_dir / filename
                if download_image(page, urls[i], save_path):
                    stats["success"] += 1
                else:
                    stats["failed"] += 1
        finally:
            browser.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Download cart photos from photo service sites")
    parser.add_argument("--site", choices=list(SITES.keys()), default="8122",
                        help="Site to use (default: 8122)")
    parser.add_argument("-o", "--output", default="./downloads",
                        help="Output directory (default: ./downloads)")
    parser.add_argument("-n", "--limit", type=int, default=None,
                        help="Max number of photos to download (default: all)")
    parser.add_argument("--analyze", action="store_true",
                        help="Analyze site structure instead of downloading")
    parser.add_argument("--url", default=None,
                        help="Override cart URL for analysis")
    parser.add_argument("--cookies", default=None,
                        help="Path to JSON file with cookies (Playwright format). Skips login if provided.")
    args = parser.parse_args()

    email = os.environ.get("SITE_EMAIL")
    password = os.environ.get("SITE_PASSWORD")
    if not args.cookies and (not email or not password):
        log.error("Set SITE_EMAIL and SITE_PASSWORD environment variables, or use --cookies")
        sys.exit(1)

    if args.analyze:
        site_key = args.site
        if args.url:
            SITES[site_key]["cart_url"] = args.url
            SITES[site_key]["name"] = args.url

        log.info(f"Analyzing site: {SITES[site_key]['name']}")
        result = run_analyze(site_key, email, password, args.cookies)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    download_dir = Path(args.output)
    download_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Site: {SITES[args.site]['name']}")
    log.info(f"Download directory: {download_dir.resolve()}")
    if args.limit:
        log.info(f"Limit: {args.limit} photos")

    stats = run_download(args.site, email, password, download_dir, args.limit, args.cookies)

    log.info("=" * 50)
    log.info("Download complete!")
    log.info(f"  Success: {stats['success']}")
    log.info(f"  Failed:  {stats['failed']}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
