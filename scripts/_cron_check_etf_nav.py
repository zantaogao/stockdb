import duckdb, os, glob
# find the ETF nav db
cands = glob.glob(os.path.expanduser('~/.hermes/stockdb/**/*.db'), recursive=True) + \
        glob.glob(os.path.expanduser('~/.hermes/stockdb/**/*.duckdb'), recursive=True)
for p in cands:
    if os.path.getsize(p) == 0:
        continue
    hdr = open(p, 'rb').read(16)
    try:
        if b'DUCK' in hdr or p.endswith('.duckdb'):
            con = duckdb.connect(p, read_only=True)
        elif hdr.startswith(b'SQLite format 3'):
            import sqlite3
            con = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
        else:
            continue
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()] if 'sqlite' in str(type(con)) or isinstance(con, object) else []
        # duckdb also supports sqlite_master query
        etf_tabs = [t for t in tables if 'etf' in t.lower() or 'fund' in t.lower()]
        for t in etf_tabs:
            try:
                cols = [r[1] if hasattr(r,'__len__') else r for r in con.execute(f"PRAGMA table_info({t})").fetchall()]
                dcol = None
                for c in cols:
                    cs = str(c).lower()
                    if cs in ('trade_date','nav_date','date','end_date'):
                        dcol = c; break
                if dcol:
                    mx = con.execute(f"SELECT MAX({dcol}), COUNT(*) FROM {t}").fetchone()
                    print(p, t, 'rows/val:', mx)
            except Exception as e:
                print(p, t, 'ERR', e)
        con.close()
    except Exception as e:
        print(p, 'OPEN-ERR', repr(e)[:80])
