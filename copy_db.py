"""Copy jobs / subscribers / seen links from your old database into the new one.
Run AFTER the new app has started once (so its tables exist):
  /opt/jobnova/venv/bin/python copy_db.py "OLD_DATABASE_URL" "sqlite:////opt/jobnova/data/jobnova.db"
Old URL = the DATABASE_URL from Render (or Aiven). It is read only, nothing is changed there.
"""
import sys
from sqlalchemy import create_engine, MetaData, select, delete, text

def norm(u):
    if u.startswith("postgres://"): return u.replace("postgres://", "postgresql+psycopg://", 1)
    if u.startswith("postgresql://"): return u.replace("postgresql://", "postgresql+psycopg://", 1)
    return u

if len(sys.argv) != 3: sys.exit(__doc__)
src, dst = create_engine(norm(sys.argv[1])), create_engine(norm(sys.argv[2]))
ms, md = MetaData(), MetaData()
ms.reflect(src); md.reflect(dst)

for name in ("job", "job_subscribers", "seen_link"):
    if name not in ms.tables or name not in md.tables:
        print(f"skip {name} (missing on one side)"); continue
    ts, td = ms.tables[name], md.tables[name]
    cols = [c.name for c in td.columns if c.name in ts.columns]
    with src.connect() as c:
        rows = [{k: r[k] for k in cols} for r in c.execute(select(*[ts.c[k] for k in cols])).mappings()]
    with dst.begin() as c:
        c.execute(delete(td))
        for i in range(0, len(rows), 500):
            c.execute(td.insert(), rows[i:i + 500])
        if dst.dialect.name == "postgresql" and "id" in td.columns and rows:
            c.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}','id'), (SELECT max(id) FROM {name}))"))
    print(f"copied {len(rows)} rows into {name}")
print("Done.")
