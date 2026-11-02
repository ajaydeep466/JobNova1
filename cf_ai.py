"""Cloudflare Workers AI for JobNova, with hard daily limits.

Loaded from app.py with two lines. If CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are not set,
nothing changes and the app keeps using OpenRouter / OpenAI / Claude.

Daily limits (counted per UTC day, saved in data/ai_usage.json so a restart does not reset them):
  DAILY_AI_LIMIT   = notices sent to the AI per day   (default 30)
  DAILY_POST_LIMIT = new automatic posts per day       (default 20)
Posts you write by hand in /admin/ are never limited.
"""
import os, json, hmac, time, logging, threading, requests
from datetime import datetime, timezone
from flask import jsonify, request

ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
MODEL = os.environ.get("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct").strip()
MAX_PROMPT_CHARS = int(os.environ.get("CF_MAX_PROMPT_CHARS", "12000"))   # keeps input inside the model window
MAX_OUT_TOKENS = int(os.environ.get("CF_MAX_OUT_TOKENS", "1800"))
DAILY_AI_LIMIT = int(os.environ.get("DAILY_AI_LIMIT", "30"))
DAILY_POST_LIMIT = int(os.environ.get("DAILY_POST_LIMIT", "20"))
QUOTA_FILE = os.environ.get("QUOTA_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ai_usage.json")

_lock = threading.Lock()


class QuotaReached(Exception):
    pass


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read():
    try:
        with open(QUOTA_FILE) as f:
            d = json.load(f)
    except Exception:
        d = {}
    if d.get("date") != _today():
        d = {"date": _today(), "ai": 0, "posts": 0, "blocked": False}
    return d


def _write(d):
    os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
    tmp = QUOTA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, QUOTA_FILE)


def quota_ok():
    with _lock:
        d = _read()
        return not d["blocked"] and d["ai"] < DAILY_AI_LIMIT and d["posts"] < DAILY_POST_LIMIT


def quota_add(ai=0, posts=0, blocked=None):
    with _lock:
        d = _read()
        d["ai"] += ai
        d["posts"] += posts
        if blocked is not None:
            d["blocked"] = blocked
        _write(d)


def quota_status():
    with _lock:
        d = _read()
    return {"day_utc": d["date"], "ai_used": d["ai"], "ai_limit": DAILY_AI_LIMIT,
            "posts_today": d["posts"], "post_limit": DAILY_POST_LIMIT,
            "blocked_by_cloudflare": d["blocked"], "model": MODEL}


def cf_llm(prompt, max_tokens=2500, timeout=90):
    """One prompt to Cloudflare Workers AI, returns the reply text."""
    if _read()["blocked"]:                     # Cloudflare already said "allowance used up" today: do not even ask
        raise RuntimeError("Cloudflare AI free allowance already used up today")
    prompt = prompt[:MAX_PROMPT_CHARS]
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{MODEL}"
    r = requests.post(url, timeout=timeout, headers={"Authorization": f"Bearer {API_TOKEN}"},
                      json={"messages": [{"role": "user", "content": prompt}],
                            "max_tokens": min(max_tokens, MAX_OUT_TOKENS)})
    body = r.text
    if r.status_code == 429 or '"code":4006' in body.replace(" ", ""):
        logging.getLogger("cf_ai").warning("Cloudflare AI HTTP %s: %s", r.status_code, body[:300])
        if '"code":4006' in body.replace(" ", "") or "daily free allocation" in body.lower():
            quota_add(blocked=True)   # Cloudflare's own free allowance is used up: stop until the next UTC day
            raise RuntimeError("Cloudflare AI free daily allowance used up")
        raise RuntimeError(f"Cloudflare AI busy (HTTP {r.status_code}), will retry on the next run")
    if r.status_code != 200:
        raise RuntimeError(f"Cloudflare AI HTTP {r.status_code}: {r.text[:200]}")
    res = r.json().get("result") or {}
    out = res.get("response")
    if out is None:
        out = ((res.get("choices") or [{}])[0].get("message") or {}).get("content")
    if isinstance(out, (dict, list)):
        out = json.dumps(out)
    return out or ""


def install_cloudflare_ai(app, g):
    """g = globals() of app.py. Swaps in the Cloudflare AI call and the daily limits."""
    try:    # safety: the auto-fetch interval can never fall below 1 hour (0 hours would mean every second)
        g["FETCH_EVERY_HOURS"] = max(1, int(g.get("FETCH_EVERY_HOURS") or 3))
    except Exception:
        g["FETCH_EVERY_HOURS"] = 3
    if not (ACCOUNT_ID and API_TOKEN):
        return
    g["AI_PROVIDER"] = "cloudflare"
    g["AI_MODEL"] = MODEL                      # only used for the label shown in the fetch report

    check = {"until": 0.0}

    def llm(prompt, max_tokens=2500, timeout=90):
        if prompt.startswith("Reply with the word ok"):     # the app's key check at the start of every run
            if time.time() < check["until"]:
                return "ok"                                  # worked within the last hour: do not spend allowance on it again
            out = cf_llm(prompt, max_tokens, timeout)
            check["until"] = time.time() + 3600
            return out
        return cf_llm(prompt, max_tokens, timeout)

    orig_find, orig_read = g["find_links"], g["read_notice"]
    orig_extract, orig_save = g["ai_extract"], g["save_notice"]

    def find_links(src):
        return orig_find(src) if quota_ok() else []      # limit reached: do not even look at the sources

    def read_notice(url):
        if not quota_ok():
            raise QuotaReached("daily limit reached")
        return orig_read(url)

    def ai_extract(label, text):
        quota_add(ai=1)
        try:
            return orig_extract(label, text)
        except ValueError:
            return None        # unreadable AI answer: skip this notice instead of retrying it forever

    def save_notice(*a, **k):
        ok = orig_save(*a, **k)
        if ok:
            quota_add(posts=1)
        return ok

    orig_fetch = g["fetch_jobs"]

    def fetch_jobs():
        if not quota_ok():
            g["FETCH_REPORT"]["stopped"] = "daily limit reached: " + json.dumps(quota_status())
            return 0
        g["FETCH_REPORT"].pop("stopped", None)
        return orig_fetch()

    g.update(fetch_jobs=fetch_jobs, llm=llm, find_links=find_links, read_notice=read_notice, ai_extract=ai_extract, save_notice=save_notice)

    @app.route("/api/ai-quota")
    def ai_quota():
        key = os.environ.get("ADMIN_KEY", "")
        if key and not hmac.compare_digest(request.args.get("key", "").encode(), key.encode()):
            return "Not found", 404
        if request.args.get("reset") == "1":
            quota_add(blocked=False)
        return jsonify(quota_status())
