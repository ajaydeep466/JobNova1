"""Website look settings (buttons, menu tabs, popup, festival bar, own ad spaces) kept in the database,
so the nightly backup covers them. Edited from /admin/site, applied by site_ui.py."""
import io, json, time, copy
from datetime import datetime, date

TABS = []                                 # menu tab names, filled by site_ui
_M, _cache = {}, {"t": 0, "v": None}
ADS = (("top", "Top of every page (under the menu)"), ("side", "Side column on post pages"),
       ("bottom", "Bottom of every page (above the footer)"))


def _fest(name, emoji, msg, start="", end="", on=False):
    return {"name": name, "emoji": emoji, "message": msg, "button": "Latest jobs", "url": "/list/jobs",
            "enabled": on, "start": start, "end": end}


DEFAULTS = {
    "bot_enabled": False,                 # the automatic bot (crawl official sites + AI posts) is OFF: you post by hand
    "hide_tabs": [], "auto_hide_empty": False, "custom_tabs": [],
    "show": {"login": False, "subscribe_strip": True, "subscribe_card": True, "telegram_btn": True,
             "whatsapp_btn": True, "whatsapp_float": True, "share_buttons": True, "closing_soon": True, "apply_button": True},
    "popup": {"enabled": True, "delay": 8, "days": 7, "title": "Get new government jobs by email",
              "text": "Free alerts with the last date. No spam."},
    "festival_bar": True,
    "festivals": [
        _fest("Republic Day", "🇮🇳", "Happy Republic Day from JobNova!", "01-24", "01-27", True),
        _fest("Holi", "🎨", "Happy Holi! Wishing you a colourful year ahead."),
        _fest("Raksha Bandhan", "🧵", "Happy Raksha Bandhan from JobNova!"),
        _fest("Independence Day", "🇮🇳", "Happy Independence Day! Jai Hind.", "08-13", "08-16", True),
        _fest("Teachers' Day", "📚", "Happy Teachers' Day from JobNova!", "09-04", "09-06", True),
        _fest("Gandhi Jayanti", "🕊️", "Gandhi Jayanti greetings from JobNova.", "10-01", "10-03", True),
        _fest("Navratri", "🔱", "Happy Navratri from JobNova!"),
        _fest("Dussehra", "🏹", "Happy Dussehra from JobNova!"),
        _fest("Diwali", "🪔", "Happy Diwali! Wishing you a bright and successful year."),
        _fest("Eid", "🌙", "Eid Mubarak from JobNova!"),
        _fest("Children's Day", "🎈", "Happy Children's Day!", "11-13", "11-15", True),
        _fest("Christmas", "🎄", "Merry Christmas from JobNova!", "12-24", "12-26", True),
        _fest("New Year", "🎆", "Happy New Year! Wishing you a successful year ahead.", "12-30", "01-02", True),
        _fest("Custom 1", "✨", ""), _fest("Custom 2", "✨", ""),
    ],
    "ads": {k: {"enabled": False, "image_id": 0, "link": "", "text": "", "alt": "", "label": True} for k, _ in ADS},
}


def _merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def init(db):
    if _M:
        return

    class SiteSetting(db.Model):
        __tablename__ = "site_setting"
        key = db.Column(db.String(50), primary_key=True)
        value = db.Column(db.Text)

    class SiteAsset(db.Model):
        __tablename__ = "site_asset"
        id = db.Column(db.Integer, primary_key=True)
        data = db.Column(db.LargeBinary)
        ts = db.Column(db.DateTime, default=datetime.utcnow)

    _M.update(db=db, S=SiteSetting, A=SiteAsset)


def ready():
    return bool(_M) and bool(TABS)


def get():
    if _cache["v"] is not None and time.time() - _cache["t"] < 10:
        return _cache["v"]
    v = copy.deepcopy(DEFAULTS)
    if _M:
        try:
            row = _M["S"].query.get("site")
            if row and row.value:
                v = _merge(v, json.loads(row.value))
        except Exception:
            _M["db"].session.rollback()
    _cache.update(t=time.time(), v=v)
    return v


def save(d):
    S, db = _M["S"], _M["db"]
    row = S.query.get("site") or S(key="site")
    row.value = json.dumps(d)
    db.session.add(row)
    db.session.commit()
    _cache.update(t=0, v=None)


def asset_add(data):
    a = _M["A"](data=data)
    _M["db"].session.add(a)
    _M["db"].session.commit()
    return a.id


def asset_get(i):
    return _M["A"].query.get(i) if _M else None


def asset_delete(i):
    a = asset_get(i) if i else None
    if a:
        _M["db"].session.delete(a)
        _M["db"].session.commit()


def process_image(raw):
    """Check it is a real picture, resize to at most 1200 px wide, strip metadata, return JPEG bytes."""
    from PIL import Image
    try:
        Image.open(io.BytesIO(raw)).verify()
        im = Image.open(io.BytesIO(raw))
        if im.width * im.height > 40_000_000:
            raise ValueError("Picture is too large in pixels.")
        im.load()
    except ValueError:
        raise
    except Exception:
        raise ValueError("That file is not a valid picture (use JPG, PNG or WebP).")
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.width > 1200:
        im = im.resize((1200, max(1, round(im.height * 1200 / im.width))))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def _md(v):
    p = v.split("-")
    if len(p) == 2:
        return None, int(p[0]), int(p[1])
    if len(p) == 3:
        return int(p[0]), int(p[1]), int(p[2])
    raise ValueError


def valid_date(v):
    """'' or 'MM-DD' (every year) or 'YYYY-MM-DD' (one time only)."""
    if not v:
        return True
    try:
        y, m, d = _md(v)
        date(y or 2024, m, d)
        return True
    except Exception:
        return False


def festival_active(f, today):
    if not (f.get("enabled") and f.get("start") and f.get("end")):
        return False
    try:
        (sy, sm, sd), (ey, em, ed) = _md(f["start"]), _md(f["end"])
        if sy and ey:
            return date(sy, sm, sd) <= today <= date(ey, em, ed)
        if sy or ey:
            return False
        md, a, b = (today.month, today.day), (sm, sd), (em, ed)
        return a <= md <= b if a <= b else (md >= a or md <= b)
    except Exception:
        return False
