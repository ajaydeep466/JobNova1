"""Headless-browser fallback for pages that build their links with JavaScript.

The normal fast fetch is always tried first. Chrome is used only when:
  - a source page gives NO usable links, or
  - a notice page gives almost no text (under 200 characters).
It uses the same honest bot name as the rest of the app and respects robots.txt.
Safety for a 1 GB machine: one page at a time, skipped if free memory is low,
and at most JS_RENDER_DAILY_LIMIT pages a day. Without Playwright installed it does nothing.
Settings: JS_RENDER=1, JS_RENDER_DAILY_LIMIT=40, JS_MIN_FREE_MB=250
Installed from app.py (second add-on).
"""
import os, re, sys, hmac, threading, subprocess
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from flask import request, jsonify

ENABLED = os.environ.get("JS_RENDER", "1") == "1"
DAILY_LIMIT = int(os.environ.get("JS_RENDER_DAILY_LIMIT", "40"))
MIN_FREE_MB = int(os.environ.get("JS_MIN_FREE_MB", "250"))
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js_render.py")
_lock = threading.Lock()
_state = {"day": "", "n": 0, "warned": False}


def _free_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 10 ** 6          # unknown system: do not block


def render_html(url, ua, log=None):
    """Final HTML of a page after its JavaScript ran, or '' if not possible."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _lock:
        if _state["day"] != day:
            _state.update(day=day, n=0)
        if _state["n"] >= DAILY_LIMIT:
            return ""
        if _free_mb() < MIN_FREE_MB:
            if log: log.warning("JS render skipped: low memory (%s MB free)", _free_mb())
            return ""
        _state["n"] += 1
        lax = "0"
        try:
            from ssl_fix import _allowed
            lax = "1" if _allowed(urlparse(url).hostname) else "0"
        except Exception:
            pass
        try:
            p = subprocess.run([sys.executable, SCRIPT, url, ua, lax], capture_output=True,
                               text=True, encoding="utf-8", timeout=75)
        except subprocess.TimeoutExpired:
            if log: log.warning("JS render timed out: %s", url)
            return ""
        if p.returncode != 0:
            if log and not _state["warned"]:
                _state["warned"] = True
                log.warning("JS render failed (is Playwright installed? run install_browser.sh): %s", (p.stderr or "")[-300:])
            return ""
        return p.stdout


def _anchors(html, base_url, g):
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        href = urljoin(base_url, a["href"]).split("#")[0]
        yield label, href


def links_from_html(html, base_url, g):
    out = {}
    for label, href in _anchors(html, base_url, g):
        if not g["crawl_ok"](href, base_url) or href.rstrip("/") == base_url.rstrip("/"):
            continue
        if g["LINK_WORDS"].search(label) or href.lower().split("?")[0].endswith(".pdf"):
            out.setdefault(href, label[:200])
    return list(out.items())[:g["MAX_LINKS_PER_SOURCE"]]


def _analyse(html, base_url, g):
    rows = [(l, h) for l, h in _anchors(html, base_url, g)]
    usable = [(l, h) for l, h in rows if g["crawl_ok"](h, base_url) and h.rstrip("/") != base_url.rstrip("/")]
    matched = [1 for l, h in usable if g["LINK_WORDS"].search(l) or h.lower().split("?")[0].endswith(".pdf")]
    rest = [f"{l[:60]} -> {h[:90]}" for l, h in usable if not (g["LINK_WORDS"].search(l) or h.lower().split("?")[0].endswith(".pdf"))]
    return {"anchors": len(rows), "usable": len(usable), "matched": len(matched), "sample_not_matched": rest[:12]}


def install_js_render(g):
    """g = globals() of app.py."""
    if not ENABLED:
        return
    app, ua = g["app"], g["BOT_UA"]
    log = app.logger
    orig_find, orig_read = g["find_links"], g["read_notice"]

    def find_links(src):
        out = orig_find(src)                       # normal fetch first (errors such as 403 pass through)
        if out or not g["robots_ok"](src["url"]):
            return out
        html = render_html(src["url"], ua, log)
        if not html:
            return out
        found = links_from_html(html, src["url"], g)
        log.info("JS render %s: %d links", src.get("name"), len(found))
        return found

    def read_notice(url):
        text, apply_link = orig_read(url)
        if len(text) >= 200 or url.lower().split("?")[0].endswith(".pdf") or not g["robots_ok"](url):
            return text, apply_link
        html = render_html(url, ua, log)
        if not html:
            return text, apply_link
        soup = BeautifulSoup(html, "html.parser")
        new_link = ""
        for a in soup.find_all("a", href=True):
            if re.search(r"apply online|apply now|online application|registration", a.get_text(" ", strip=True), re.I):
                h = urljoin(url, a["href"])
                if g["crawl_ok"](h, url):
                    new_link = h
                    break
        for t in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "iframe"]):
            t.decompose()
        new_text = soup.get_text("\n", strip=True)
        return (new_text if len(new_text) > len(text) else text), (apply_link or new_link)

    g["find_links"], g["read_notice"] = find_links, read_notice

    @app.route("/api/source-debug")
    def source_debug():
        """?key=ADMIN_KEY&name=SSC  (add &render=1 to also test the headless browser)"""
        key = os.environ.get("ADMIN_KEY", "")
        if key and not hmac.compare_digest(request.args.get("key", "").encode(), key.encode()):
            return "Not found", 404
        name = request.args.get("name", "").lower()
        src = next((s for s in g["SOURCES"] + g.get("PRIVATE_SOURCES", []) if s["name"].lower() == name), None)
        if not src:
            return jsonify({"error": "unknown name", "names": [s["name"] for s in g["SOURCES"]]})
        rep = {"source": src["name"], "url": src["url"]}
        try:
            rep["static"] = _analyse(g["http_get"](src["url"]).text, src["url"], g)
        except Exception as e:
            rep["static_error"] = str(e)[:200]
        if request.args.get("render") == "1":
            html = render_html(src["url"], ua, log)
            rep["rendered"] = _analyse(html, src["url"], g) if html else "not available (see journal)"
        return jsonify(rep)
