"""Applies the /admin/site settings to every public page: hides or shows buttons and menu tabs, removes the
login link, adds the subscribe popup, the festival bar and your own ad spaces. Installed from app.py."""
import re, time
from html import escape
from flask import Response
import site_settings as ss

CSS = """<style id="jn-ui">
.jn-fest{background:var(--head,#0d2b45);color:#fff;text-align:center;padding:9px 12px;font-weight:700}
.jn-fest .btn{margin-left:8px;padding:4px 12px;background:#ffb703;color:#10202e}
.jn-adw{margin:12px auto}.jn-ad{background:#fff;border:1px solid #d9e0e8;border-radius:6px;padding:8px;text-align:center}
.jn-ad img{max-width:100%;height:auto;border-radius:4px}.jn-ad p{margin:6px 0 0;font-weight:600}
.jn-ad small{display:block;color:#5b6876;font-size:11px;margin-bottom:4px}
.jn-pop{position:fixed;inset:0;background:#0009;display:flex;align-items:center;justify-content:center;z-index:99;padding:16px}
.jn-pop[hidden]{display:none}.jn-pop-box{background:#fff;color:#1b2733;border-radius:8px;padding:20px;max-width:380px;width:100%;position:relative}
.jn-pop-box h3{margin:0 28px 6px 0}.jn-pop-box p{margin:0 0 12px;color:#44515e}
.jn-pop-box form{display:flex;flex-wrap:wrap;gap:8px}.jn-pop-box input{flex:1 1 150px;min-width:0;padding:10px;border:1px solid #bbb;border-radius:5px;font:inherit}
.jn-x{position:absolute;right:8px;top:4px;border:0;background:none;font-size:28px;line-height:1;cursor:pointer;color:#555}
</style>"""


def _rm(pat, html, flags=re.S):
    return re.sub(pat, "", html, flags=flags)


def _tab(t):
    ext = ' target="_blank" rel="noopener"' if t["url"].startswith("http") else ""
    return f'<a href="{escape(t["url"])}" style="--c:#5b6876"{ext}>{escape(t["label"])}</a>\n'


def _ad(a):
    if not a.get("enabled") or not (a.get("image_id") or a.get("text")):
        return ""
    inner = ""
    if a.get("image_id"):
        inner += f'<img src="/media/{int(a["image_id"])}.jpg" alt="{escape(a.get("alt", ""))}" loading="lazy">'
    if a.get("text"):
        inner += f'<p>{escape(a["text"])}</p>'
    if a.get("link"):
        inner = f'<a href="{escape(a["link"])}" target="_blank" rel="sponsored noopener">{inner}</a>'
    label = "<small>Advertisement</small>" if a.get("label", True) else ""
    return f'<div class="wrap jn-adw"><div class="jn-ad">{label}{inner}</div></div>'


def _festival(s, today):
    if not s.get("festival_bar"):
        return ""
    out = ""
    for f in s["festivals"]:
        if ss.festival_active(f, today) and f.get("message"):
            btn = (f' <a class="btn" href="{escape(f["url"])}">{escape(f["button"])}</a>' if f.get("url") and f.get("button") else "")
            out += f'<div class="jn-fest">{escape(f.get("emoji", ""))} {escape(f["message"])}{btn}</div>'
            if out.count("jn-fest") >= 2:
                break
    return out


def _popup(p):
    if not p.get("enabled"):
        return ""
    return (f'<div id="jnpop" class="jn-pop" hidden role="dialog" aria-modal="true" aria-label="Subscribe"><div class="jn-pop-box">'
            f'<button type="button" class="jn-x" aria-label="Close">&times;</button><h3>{escape(p["title"])}</h3><p>{escape(p["text"])}</p>'
            f'<form method="post" action="/subscribe"><input type="email" name="email" placeholder="Your email address" required autocomplete="email">'
            f'<button class="btn" type="submit">Subscribe</button></form></div></div>'
            f'<script>(function(){{var k="jn_pop",d={int(p["days"])}*864e5;try{{if(Date.now()<(+localStorage.getItem(k)||0))return}}catch(e){{}}'
            f'setTimeout(function(){{var p=document.getElementById("jnpop");if(!p)return;p.hidden=false;'
            f'function c(){{p.hidden=true;try{{localStorage.setItem(k,Date.now()+d)}}catch(e){{}}}}'
            f'p.querySelector(".jn-x").onclick=c;p.addEventListener("click",function(e){{if(e.target===p)c()}});'
            f'document.addEventListener("keydown",function(e){{if(e.key==="Escape")c()}});'
            f'p.querySelector("form").addEventListener("submit",function(){{try{{localStorage.setItem(k,Date.now()+d*4)}}catch(e){{}}}})}},{int(p["delay"])}*1000)}})();</script>')


def transform(html, s, counts, today):
    """Pure function: page HTML in, changed page HTML out. counts() -> {tab: number of posts} (or None)."""
    show = s["show"]
    if not show.get("login"):
        html = _rm(r'<span class="acct">.*?</span>', html)
    hidden = set(s["hide_tabs"])
    if s.get("auto_hide_empty") and counts:
        hidden |= {t for t, n in counts().items() if n == 0}
    hidden.discard("Home")
    m = re.search(r'<nav class="nav".*?</nav>', html, re.S)
    if m and hidden:
        nav = m.group(0)
        for t in hidden:
            nav = _rm(r'<a href="[^"]*" style="[^"]*">' + re.escape(escape(t, quote=False)) + r'</a>\n?', nav)
        html = html[:m.start()] + nav + html[m.end():]
    custom = [t for t in s.get("custom_tabs", []) if t.get("label") and t.get("url")]
    if custom:
        links = "".join(_tab(t) for t in custom)
        html = re.sub(r'(<nav class="nav".*?)(</div></nav>)', lambda mm: mm.group(1) + links + mm.group(2), html, count=1, flags=re.S)
    if not show.get("subscribe_strip"):
        html = _rm(r'<div class="sub">.*?</form></div></div>\n?', html)
    if not show.get("telegram_btn"):
        html = _rm(r'<a class="btn tg"[^>]*>.*?</a>', html)
    if not show.get("whatsapp_btn"):
        html = _rm(r'<a class="btn wa"[^>]*>Join WhatsApp channel</a>', html)
    if not show.get("whatsapp_float"):
        html = _rm(r'<a class="fab"[^>]*>.*?</a>\n?', html)
    if not show.get("share_buttons"):
        html = _rm(r'<div class="share">.*?</div>', html)
    if not show.get("closing_soon"):
        html = _rm(r'<h2 class="h">Closing soon</h2><div class="strip">.*?</div>', html)
    if not show.get("apply_button"):
        html = _rm(r'<p><a href="[^"]*" target="_blank" rel="nofollow noopener" class="btn">Apply / Official Notification</a></p>', html)
    if not show.get("subscribe_card"):
        def card(mm):
            c = _rm(r'<form method="post" action="/subscribe">.*?</form>', mm.group(0))
            return c if '<a class="btn' in c else ""
        html = re.sub(r'<section class="cta">.*?</section>', card, html, flags=re.S)
    html = html.replace("</head>", CSS + "</head>", 1)
    html = html.replace("</nav>", "</nav>" + _festival(s, today), 1)
    ads = s["ads"]
    html = html.replace('<main id="main"', _ad(ads["top"]) + '<main id="main"', 1)
    html = html.replace("<aside>", "<aside>" + _ad(ads["side"]), 1)
    html = html.replace("</main>", _ad(ads["bottom"]) + "</main>", 1)
    return html.replace("</body>", _popup(s["popup"]) + "</body>", 1)


def install_site_ui(g):
    """g = globals() of app.py."""
    app, db, Job = g["app"], g["db"], g["Job"]
    ss.init(db)
    ss.TABS[:] = ["Home"] + [v[0] for v in g["KINDS"].values()] + [label for label, _ in g["TOPICS"]]
    orig, cache = g["render_page"], {"t": 0, "v": {}}
    orig_fetch = g["fetch_jobs"]

    def fetch_jobs():
        # The bot is OFF unless you switch it on in /admin/site. The 3-hourly job still sends e-mail alerts for your own posts.
        if not ss.get().get("bot_enabled"):
            g["FETCH_REPORT"]["stopped"] = "The automatic bot is switched off in Site settings."
            return 0
        g["FETCH_REPORT"].pop("stopped", None)
        return orig_fetch()

    g["fetch_jobs"] = fetch_jobs

    def counts():
        if time.time() - cache["t"] > 60:
            from sqlalchemy import or_
            out = {}
            for k, v in g["KINDS"].items():
                out[v[0]] = Job.query.filter(g["kind_filter"](k)).count()
            for label, term in g["TOPICS"]:
                words = g["SEARCH_WORDS"].get(term, [term])
                out[label] = Job.query.filter(or_(*[Job.title.ilike(f"%{w}%") for w in words])).count()
            cache.update(t=time.time(), v=out)
        return cache["v"]

    def render_page(*a, **k):
        html = orig(*a, **k)
        try:
            return transform(html, ss.get(), counts, g["today_ist"]())
        except Exception:
            app.logger.exception("site_ui failed, showing the normal page")
            return html

    g["render_page"] = render_page

    @app.route("/media/<int:asset_id>.jpg")
    def site_media(asset_id):
        a = ss.asset_get(asset_id)
        if not a:
            return "Not found", 404
        r = Response(a.data, mimetype="image/jpeg")
        r.headers["Cache-Control"] = "public, max-age=604800, immutable"
        return r
