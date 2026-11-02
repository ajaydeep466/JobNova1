"""JobNova admin panel: login, list, add, edit, delete posts.
Registered from app.py with:  from admin_panel import register_admin; register_admin(app, db, Job, ...)
"""
import os, re, json, time, secrets, hmac
from datetime import datetime, date
from urllib.parse import quote
from flask import request, session, redirect, Response
from markupsafe import escape

_attempts = {}   # ip -> [timestamps] for login rate limiting


LINK_FIELDS = [("extended_link", "Extended Link"), ("apply_link", "Apply Online"),
               ("notice_link", "Official Notification PDF"), ("site_link", "Official Website")]
LINKS_RE = re.compile(r"<!--links-->.*?<!--/links-->", re.S)


def _links_block(links):
    """The 'Important links' list shown at the end of a post. links = [(label, url), ...]"""
    if not links:
        return ""
    items = "".join(f'<li><b>{escape(label)}:</b> <a href="{escape(url)}">Click here</a></li>' for label, url in links)
    return f"<!--links--><h2>Important links</h2><ul>{items}</ul><!--/links-->"


def _picked_links(vals):
    return [(label, vals[key]) for key, label in LINK_FIELDS if vals.get(key)]


def _main_link(vals):
    """The big Apply button on the post: your own 'Official link', else Apply Online, Notification, Website, Extended."""
    return (vals.get("official_link") or vals.get("apply_link") or vals.get("notice_link")
            or vals.get("site_link") or vals.get("extended_link") or "")


def _manual_json(links):
    return json.dumps({"manual": True, "links": [{"label": l, "url": u} for l, u in links]})


def _saved_links(job):
    try:
        return {x["label"]: x["url"] for x in (json.loads(job.ai_json or "{}").get("links") or [])} if job else {}
    except Exception:
        return {}


def _lite_to_html(text):
    """Turns simple text into HTML. '## Heading', '- bullet', blank line = new paragraph.
    If the text already contains HTML tags it is returned unchanged."""
    text = (text or "").replace("\r\n", "\n").strip()
    if re.search(r"</?(p|h2|h3|ul|ol|li|table|b|strong|a)\b", text, re.I):
        return text
    out, bullets, paras = [], [], []

    def flush_paras():
        if paras:
            out.append(f"<p>{escape(' '.join(paras))}</p>"); paras.clear()

    def flush_bullets():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{escape(b)}</li>" for b in bullets) + "</ul>"); bullets.clear()

    for line in text.split("\n"):
        s = line.strip()
        if not s:
            flush_paras(); flush_bullets()
        elif s.startswith("## "):
            flush_paras(); flush_bullets(); out.append(f"<h2>{escape(s[3:])}</h2>")
        elif s.startswith(("- ", "* ")):
            flush_paras(); bullets.append(s[2:].strip())
        else:
            flush_bullets(); paras.append(s)
    flush_paras(); flush_bullets()
    return "".join(out)


def register_admin(app, db, Job, STATES, safe_html, SITE_URL):
    password = lambda: (os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_KEY") or "")

    def client_ip():
        # Only cloudflared (on this machine) can reach gunicorn, so this header is trustworthy.
        return request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    def csrf_ok():
        return hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x"))

    def page(title, body):
        html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>{escape(title)} - JobNova Admin</title><style>
body{{font:16px system-ui,sans-serif;margin:0;background:#f4f5f7;color:#222}}
header{{background:#1b2a41;color:#fff;padding:12px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}}
header a{{color:#fff;text-decoration:none;font-weight:600}} main{{max-width:760px;margin:0 auto;padding:16px}}
.card{{background:#fff;border-radius:10px;padding:14px;margin-bottom:12px;box-shadow:0 1px 3px #0002}}
label{{display:block;font-weight:600;margin:12px 0 4px}} input,select,textarea{{width:100%;box-sizing:border-box;padding:10px;font:inherit;border:1px solid #bbb;border-radius:8px}}
textarea{{min-height:320px;font-family:ui-monospace,monospace;font-size:14px}}
.btn{{display:inline-block;background:#0d6efd;color:#fff;border:0;border-radius:8px;padding:10px 16px;font:inherit;font-weight:600;text-decoration:none;cursor:pointer}}
.btn.red{{background:#c92a2a}} .btn.grey{{background:#666}} .row{{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}}
.msg{{background:#e6fcf5;border:1px solid #96f2d7;padding:10px;border-radius:8px;margin-bottom:12px}}
.err{{background:#fff0f0;border:1px solid #f5a3a3}} small{{color:#666}} h1{{font-size:20px}}
</style></head><body><header><a href="/admin/">JobNova Admin</a><a href="/admin/new">+ New post</a>
<a href="/admin/site">Site settings</a>
<a href="/" target="_blank">View site</a><a href="/admin/logout">Logout</a></header><main>{body}</main></body></html>"""
        r = Response(html)
        r.headers["Cache-Control"] = "no-store"
        return r

    def need_login():
        if session.get("is_admin"):
            return None
        return redirect("/admin/login")

    # ---------- login / logout ----------
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        err = ""
        if request.method == "POST":
            ip, now = client_ip(), time.time()
            recent = [t for t in _attempts.get(ip, []) if now - t < 600]
            _attempts[ip] = recent
            if len(recent) >= 5:
                err = "Too many tries. Wait 10 minutes."
            elif password() and hmac.compare_digest(request.form.get("password", "").encode(), password().encode()):
                session.clear(); session["is_admin"] = True; session.permanent = False
                return redirect("/admin/")
            else:
                recent.append(now); err = "Wrong password."
        body = (f'<div class="card"><h1>Admin login</h1>{f"<div class=msg err>{escape(err)}</div>" if err else ""}'
                '<form method="post"><label>Password</label><input type="password" name="password" autofocus>'
                '<div class="row"><button class="btn">Login</button></div></form></div>')
        return page("Login", body)

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("is_admin", None); session.pop("csrf", None)
        return redirect("/admin/login")

    # ---------- list ----------
    @app.route("/admin/")
    def admin_home():
        r = need_login()
        if r: return r
        q = request.args.get("q", "").strip()
        query = Job.query
        if q: query = query.filter(Job.title.ilike(f"%{q}%"))
        jobs = query.order_by(Job.posted_on.desc(), Job.id.desc()).limit(60).all()
        total = Job.query.count()
        flash = request.args.get("m", "")
        rows = "".join(
            f'<div class="card"><b>{escape(j.title)}</b><br><small>#{j.id} &middot; {escape(j.category or "")} &middot; '
            f'{escape(j.state or "")} &middot; {j.posted_on:%d %b %Y}' + (f' &middot; last date {j.last_date:%d %b %Y}' if j.last_date else "") +
            f'</small><div class="row"><a class="btn grey" href="/job/{j.id}" target="_blank">View</a>'
            f'<a class="btn" href="/admin/edit/{j.id}">Edit</a>'
            f'<form method="post" action="/admin/delete/{j.id}" onsubmit="return confirm(\'Delete this post?\')">'
            f'<input type="hidden" name="csrf" value="{csrf()}"><button class="btn red">Delete</button></form></div></div>'
            for j in jobs)
        body = (f'{f"<div class=msg>{escape(flash)}</div>" if flash else ""}'
                f'<h1>Posts ({total})</h1><form method="get"><input name="q" placeholder="Search title" value="{escape(q)}"></form><br>'
                f'{rows or "<div class=card>No posts found.</div>"}')
        return page("Posts", body)

    # ---------- form ----------
    def links_inputs(j, v):
        saved = _saved_links(j)
        out = '<label>Important links (optional)</label><small>Shown at the end of the post as a list. Fill only the links you have.</small>'
        for key, label in LINK_FIELDS:
            val = v.get(key, "") if v else saved.get(label, "")
            out += f'<label>{label}</label><input name="{key}" type="url" placeholder="https://..." value="{escape(val or "")}">'
        return out

    def form_html(j=None, err="", vals=None):
        v = vals or {}
        g = lambda k, d="": escape(v.get(k, getattr(j, k, d) if j else d) or "")
        cats = [("all-india", "All India"), ("bank", "Bank"), ("railway", "Railway")]
        cur_cat = v.get("category") or (j.category if j else "all-india")
        cat_opts = "".join(f'<option value="{c}" {"selected" if c == cur_cat else ""}>{n}</option>' for c, n in cats)
        cur_state = v.get("state") or (j.state if j else "All India")
        st_opts = "".join(f'<option {"selected" if s == cur_state else ""}>{escape(s)}</option>' for s in (["All India"] + [s for s in STATES if s != "All India"]))
        ld = v.get("last_date") or (j.last_date.isoformat() if j and j.last_date else "")
        content = v.get("content") if "content" in v else (LINKS_RE.sub("", j.content or "").strip() if j else "")
        action = f"/admin/edit/{j.id}" if j else "/admin/new"
        return (f'<div class="card"><h1>{"Edit post" if j else "New post"}</h1>'
                f'{f"<div class=msg err>{escape(err)}</div>" if err else ""}'
                f'<form method="post" action="{action}"><input type="hidden" name="csrf" value="{csrf()}">'
                f'<label>Title *</label><input name="title" required maxlength="300" value="{g("title")}">'
                f'<small>Include words like "Admit Card", "Result" or "Answer Key" so it lands in the right tab.</small>'
                f'<label>Category</label><select name="category">{cat_opts}</select>'
                f'<label>State</label><select name="state">{st_opts}</select>'
                f'<label>Last date to apply</label><input type="date" name="last_date" value="{escape(ld)}">'
                f'<label>Official link (apply / notification)</label><input name="official_link" type="url" placeholder="https://..." value="{g("official_link")}">'
                + links_inputs(j, vals) +
                f'<label>Short description (shown in Google, max 300)</label><input name="description" maxlength="300" value="{g("description")}">'
                f'<label>Content</label><textarea name="content" required>{escape(content or "")}</textarea>'
                f'<small>Plain text works: "## Heading", "- bullet", blank line between paragraphs. HTML also works.</small>'
                f'<div class="row"><button class="btn">Save and publish</button><a class="btn grey" href="/admin/">Cancel</a></div></form></div>')

    def read_form():
        f = request.form
        vals = {k: f.get(k, "").strip() for k in ("title", "category", "state", "last_date", "official_link", "description", "content",
                                                                  *[k for k, _ in LINK_FIELDS])}
        err = ""
        if not vals["title"]: err = "Title is required."
        elif not vals["content"]: err = "Content is required."
        elif vals["official_link"] and not re.match(r"https?://", vals["official_link"], re.I): err = "Official link must start with http:// or https://"
        for key, label in LINK_FIELDS:
            if not err and vals[key] and not re.match(r"https?://", vals[key], re.I):
                err = f"{label} must start with http:// or https://"
        ld = None
        if not err and vals["last_date"]:
            try: ld = date.fromisoformat(vals["last_date"])
            except ValueError: err = "Last date is not valid."
        return vals, ld, err

    @app.route("/admin/new", methods=["GET", "POST"])
    def admin_new():
        r = need_login()
        if r: return r
        if request.method == "POST":
            if not csrf_ok(): return "Bad request", 400
            vals, ld, err = read_form()
            if not err and Job.query.filter(db.func.lower(Job.title) == vals["title"].lower()).first():
                err = "A post with this title already exists."
            if err: return page("New post", form_html(err=err, vals=vals))
            links, main = _picked_links(vals), _main_link(vals)
            html = safe_html(_lite_to_html(vals["content"])) + _links_block(links)
            job = Job(title=vals["title"][:600], category=vals["category"] or "all-india", state=vals["state"] or "All India",
                      link=main or SITE_URL, content=html, official_link=main or None,
                      description=vals["description"][:300], last_date=ld, ai_json=_manual_json(links), notified=False)
            db.session.add(job); db.session.commit()
            return redirect("/admin/?m=" + quote(f"Published: {job.title[:60]}"))
        return page("New post", form_html())

    @app.route("/admin/edit/<int:job_id>", methods=["GET", "POST"])
    def admin_edit(job_id):
        r = need_login()
        if r: return r
        job = Job.query.get_or_404(job_id)
        if request.method == "POST":
            if not csrf_ok(): return "Bad request", 400
            vals, ld, err = read_form()
            if err: return page("Edit post", form_html(job, err=err, vals=vals))
            job.title = vals["title"][:600]; job.category = vals["category"] or job.category; job.state = vals["state"] or job.state
            links = _picked_links(vals)
            job.official_link = _main_link(vals) or None; job.description = vals["description"][:300]; job.last_date = ld
            job.content = safe_html(_lite_to_html(vals["content"])) + _links_block(links)
            job.ai_json = _manual_json(links)     # edited posts are shown exactly as you wrote them
            db.session.commit()
            return redirect("/admin/?m=" + quote(f"Saved: {job.title[:60]}"))
        return page("Edit post", form_html(job))

    @app.route("/admin/delete/<int:job_id>", methods=["POST"])
    def admin_delete(job_id):
        r = need_login()
        if r: return r
        if not csrf_ok(): return "Bad request", 400
        job = Job.query.get_or_404(job_id)
        db.session.delete(job); db.session.commit()
        return redirect("/admin/?m=Deleted")

    try:
        from admin_site import register_site_admin
        register_site_admin(app, page, need_login, csrf, csrf_ok)
    except Exception:
        app.logger.exception("admin_site could not be installed")

    # Keep admin pages out of caches and search engines
    @app.after_request
    def _admin_headers(resp):
        if request.path.startswith("/admin"):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp
