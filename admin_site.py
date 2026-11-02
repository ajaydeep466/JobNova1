"""/admin/site : one page to show or hide every button, the popup, festival messages and your own ad spaces."""
import copy
from urllib.parse import quote
from markupsafe import escape
from flask import request, redirect
import site_settings as ss

SHOW_LABELS = [("login", "Log in link (top right)"), ("subscribe_strip", "Subscribe bar under the menu"),
               ("subscribe_card", "Subscribe box (Get job alerts)"), ("telegram_btn", "Join Telegram channel button"),
               ("whatsapp_btn", "Join WhatsApp channel button"), ("whatsapp_float", "Floating WhatsApp button"),
               ("share_buttons", "Share buttons (WhatsApp, Telegram, Copy link)"), ("closing_soon", "Closing soon strip on the home page"),
               ("apply_button", "Apply / Official Notification button on posts")]
MAX_PIC = 4 * 1024 * 1024
CUSTOM_TABS = 8


def _chk(name, on, label):
    return (f'<label style="font-weight:400;display:flex;gap:8px;align-items:center;margin:8px 0">'
            f'<input type="checkbox" name="{name}" value="1" style="width:auto" {"checked" if on else ""}> {escape(label)}</label>')


def _txt(label, name, val, extra=""):
    return f'<label>{escape(label)}</label><input name="{name}" value="{escape(val or "")}" {extra}>'


def _sec(title, body, opened=False):
    return f'<details class="card" {"open" if opened else ""}><summary style="font-weight:700;font-size:17px">{escape(title)}</summary>{body}</details>'


def form(s, msg=""):
    f = f'<h1>Site settings</h1>{f"<div class=msg>{escape(msg)}</div>" if msg else ""}<small>Changes show on the site within about 10 seconds.</small>'
    f += ('<form method="post" enctype="multipart/form-data">' + f'<input type="hidden" name="csrf" value="{CSRF()}">')
    body = (_chk("bot_on", s.get("bot_enabled"), "Automatic bot ON (reads official sites and writes posts with AI)")
            + "<small>Leave this OFF to post only by hand. Your own posts still get e-mailed to subscribers and sent to Telegram.</small>")
    f += _sec("Automatic bot", body, True)
    body = "".join(_chk("show_" + k, s["show"].get(k, True), lab) for k, lab in SHOW_LABELS)
    f += _sec("Buttons and bars (tick = shown)", body, True)
    body = "".join(_chk(f"tab_{i}", t not in s["hide_tabs"], t) for i, t in enumerate(ss.TABS) if t != "Home")
    body += _chk("auto_hide", s.get("auto_hide_empty"), "Also hide a tab automatically while it has no posts")
    body += ('<div style="border-top:1px solid #ddd;margin-top:12px;padding-top:6px"><b>Add your own tabs</b></div>'
             '<small>Name, then a link (https://... or /page) or just a word to search for, for example SSC. Clear both boxes to remove a tab.</small>')
    mine = s.get("custom_tabs", [])
    for i in range(CUSTOM_TABS):
        t = mine[i] if i < len(mine) else {}
        body += _txt(f"Tab {i + 1} name", f"ct{i}_label", t.get("label", ""), 'maxlength="20"') + _txt("Link or search word", f"ct{i}_url", t.get("raw", t.get("url", "")))
    f += _sec("Menu tabs (tick = shown)", "<small>Home is always shown.</small>" + body)
    p = s["popup"]
    body = (_chk("pop_on", p["enabled"], "Show the subscribe popup") + _txt("Seconds before it opens", "pop_delay", p["delay"], 'type="number" min="0" max="120"')
            + _txt("Show again after how many days", "pop_days", p["days"], 'type="number" min="1" max="90"')
            + _txt("Title", "pop_title", p["title"], 'maxlength="90"') + _txt("Message", "pop_text", p["text"], 'maxlength="160"')
            + "<small>A popup on a phone can annoy visitors and may hurt Google ranking and AdSense review. Keep the delay at 8 seconds or more.</small>")
    f += _sec("Subscribe popup", body)
    body = _chk("fest_on", s.get("festival_bar", True), "Show festival messages (master switch)")
    body += ("<small>Fixed days repeat every year with dates like 08-13. Moving festivals (Holi, Diwali, Dussehra, Eid...) need the "
             "dates for this year, written 2026-11-08. Look them up in an official calendar. Leave dates empty to keep it off.</small>")
    for i, fe in enumerate(s["festivals"]):
        name = _txt("Name", f"f{i}_name", fe["name"]) if fe["name"].startswith("Custom") else f'<b>{escape(fe["emoji"])} {escape(fe["name"])}</b>'
        body += ('<div style="border-top:1px solid #ddd;margin-top:12px;padding-top:6px">' + name + _chk(f"f{i}_on", fe["enabled"], "On")
                 + _txt("Message", f"f{i}_msg", fe["message"], 'maxlength="140"') + _txt("Button text (optional)", f"f{i}_btn", fe["button"], 'maxlength="30"')
                 + _txt("Button link (optional)", f"f{i}_url", fe["url"]) + _txt("Starts (MM-DD or YYYY-MM-DD)", f"f{i}_start", fe["start"])
                 + _txt("Ends (MM-DD or YYYY-MM-DD)", f"f{i}_end", fe["end"]) + "</div>")
    f += _sec("Festival messages", body)
    body = "<small>Your own photo or message. Photos are checked, resized to 1200 px wide and kept in the database.</small>"
    for key, lab in ss.ADS:
        a = s["ads"][key]
        pic = (f'<div><img src="/media/{int(a["image_id"])}.jpg" style="max-width:100%;max-height:130px"></div>' + _chk(f"ad_{key}_rm", False, "Remove this photo")) if a["image_id"] else ""
        body += (f'<div style="border-top:1px solid #ddd;margin-top:12px;padding-top:6px"><b>{escape(lab)}</b>' + _chk(f"ad_{key}_on", a["enabled"], "Show this space")
                 + pic + f'<label>{"Replace photo" if a["image_id"] else "Photo"} (JPG, PNG or WebP, up to 4 MB)</label><input type="file" name="ad_{key}_file" accept="image/*">'
                 + _txt("Link when tapped (optional)", f"ad_{key}_link", a["link"]) + _txt("Message (optional)", f"ad_{key}_text", a["text"], 'maxlength="200"')
                 + _txt("Photo description (for screen readers)", f"ad_{key}_alt", a["alt"], 'maxlength="100"')
                 + _chk(f"ad_{key}_label", a.get("label", True), 'Show a small "Advertisement" label') + "</div>")
    f += _sec("My own ad spaces", body)
    return f + '<div class="row"><button class="btn">Save settings</button><a class="btn grey" href="/admin/">Back</a></div></form>'


CSRF = lambda: ""


def _url_ok(v):
    return not v or v.startswith(("http://", "https://")) or (v.startswith("/") and not v.startswith("//"))


def _tab_url(v):
    """A full link, a path starting with /, or a plain word (becomes a search for that word)."""
    if v.startswith(("http://", "https://")) or (v.startswith("/") and not v.startswith("//")):
        return v
    if 2 <= len(v) <= 40 and ":" not in v:
        return "/search?q=" + quote(v)
    return ""


def _int(v, lo, hi, d):
    try:
        return max(lo, min(hi, int(v)))
    except Exception:
        return d


def apply(req):
    """Read the form into new settings and save. Returns an error text, or '' when saved."""
    f, s = req.form, copy.deepcopy(ss.get())
    s["show"] = {k: f.get("show_" + k) == "1" for k in s["show"]}
    s["hide_tabs"] = [t for i, t in enumerate(ss.TABS) if t != "Home" and f.get(f"tab_{i}") != "1"]
    s["auto_hide_empty"] = f.get("auto_hide") == "1"
    s["bot_enabled"] = f.get("bot_on") == "1"
    tabs = []
    for i in range(CUSTOM_TABS):
        lab, raw = f.get(f"ct{i}_label", "").strip()[:20], f.get(f"ct{i}_url", "").strip()
        if not lab and not raw:
            continue
        if not lab or not raw:
            return f"Tab {i + 1}: fill both the name and the link (or search word)."
        url = _tab_url(raw)
        if not url:
            return f'Tab "{lab}": use a link starting with http:// or https://, a path starting with /, or a search word (no colon).'
        tabs.append({"label": lab, "url": url, "raw": raw})
    s["custom_tabs"] = tabs
    p = s["popup"]
    p.update(enabled=f.get("pop_on") == "1", delay=_int(f.get("pop_delay"), 0, 120, 8), days=_int(f.get("pop_days"), 1, 90, 7),
             title=f.get("pop_title", "").strip()[:90] or p["title"], text=f.get("pop_text", "").strip()[:160])
    s["festival_bar"] = f.get("fest_on") == "1"
    for i, fe in enumerate(s["festivals"]):
        fe.update(enabled=f.get(f"f{i}_on") == "1", message=f.get(f"f{i}_msg", "").strip()[:140], button=f.get(f"f{i}_btn", "").strip()[:30],
                  url=f.get(f"f{i}_url", "").strip(), start=f.get(f"f{i}_start", "").strip(), end=f.get(f"f{i}_end", "").strip())
        if fe["name"].startswith("Custom"):
            fe["name"] = f.get(f"f{i}_name", "").strip()[:30] or fe["name"]
        if not _url_ok(fe["url"]):
            return f'{fe["name"]}: the button link must start with http:// or https:// (or /).'
        if not (ss.valid_date(fe["start"]) and ss.valid_date(fe["end"])):
            return f'{fe["name"]}: dates must look like 08-15 or 2026-11-08.'
    old = []
    for key, lab in ss.ADS:
        a = s["ads"][key]
        a.update(enabled=f.get(f"ad_{key}_on") == "1", link=f.get(f"ad_{key}_link", "").strip(), text=f.get(f"ad_{key}_text", "").strip()[:200],
                 alt=f.get(f"ad_{key}_alt", "").strip()[:100], label=f.get(f"ad_{key}_label") == "1")
        if not _url_ok(a["link"]):
            return f"{lab}: the link must start with http:// or https:// (or /)."
        up = req.files.get(f"ad_{key}_file")
        if up and up.filename:
            raw = up.read(MAX_PIC + 1)
            if len(raw) > MAX_PIC:
                return f"{lab}: the photo is bigger than 4 MB."
            try:
                new_id = ss.asset_add(ss.process_image(raw))
            except ValueError as e:
                return f"{lab}: {e}"
            old.append(a["image_id"]); a["image_id"] = new_id
        elif f.get(f"ad_{key}_rm") == "1":
            old.append(a["image_id"]); a["image_id"] = 0
    ss.save(s)
    for i in old:
        ss.asset_delete(i)
    return ""


def register_site_admin(app, page, need_login, csrf, csrf_ok):
    global CSRF
    CSRF = csrf

    @app.route("/admin/site", methods=["GET", "POST"])
    def admin_site():
        r = need_login()
        if r:
            return r
        if not ss.ready():
            return page("Site settings", '<div class="card">The site settings add-on is not installed yet. Add <code>site_ui</code> in app.py (see the update notes).</div>')
        if request.method == "POST":
            if not csrf_ok():
                return "Bad request", 400
            err = apply(request)
            if not err:
                return redirect("/admin/site?m=Saved")
            return page("Site settings", form(ss.get(), "Not saved: " + err))
        return page("Site settings", form(ss.get(), request.args.get("m", "")))
