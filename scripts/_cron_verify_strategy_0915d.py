import sqlite3, os, datetime
for name in ("cron.db", "executions.db"):
    p = os.path.expanduser(f"~/.hermes/cron/{name}")
    if not os.path.exists(p):
        print(name, "missing"); continue
    c = sqlite3.connect(p)
    tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print(f"\n===== {name} tables={tabs}")
    for t in tabs:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        if not any("job" in x.lower() or "run" in x.lower() or "time" in x.lower() or "event" in x.lower() for x in cols):
            continue
        try:
            rows = c.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 12").fetchall()
        except Exception as e:
            print("  ", t, "ERR", e); continue
        print(f"  -- {t} cols={cols}")
        for r in rows:
            s = str(dict(zip(cols, r)))
            if "051af" in s or "strategy" in s:
                print("     ", s[:400])
