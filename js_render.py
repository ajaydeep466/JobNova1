"""Opens one page in a headless Chrome, waits for its JavaScript, prints the final HTML.
Run by js_fix.py as a separate short-lived process, so the browser's memory is freed right after.
Usage: python js_render.py URL USER_AGENT IGNORE_CERT_ERRORS(0|1)
"""
import sys
from playwright.sync_api import sync_playwright

url, ua, lax = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
sys.stdout.reconfigure(encoding="utf-8")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
    try:
        ctx = browser.new_context(user_agent=ua, ignore_https_errors=lax)
        ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        sys.stdout.write(page.content()[:3_000_000])
    finally:
        browser.close()
