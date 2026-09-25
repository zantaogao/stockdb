import duckdb, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = duckdb.connect('tushare.db', read_only=True)
tabs = [r[0] for r in c.execute("SELECT table_name FROM information_schema.tables").fetchall()]
cand = [t for t in tabs if 'fund' in t.lower() or 'etf' in t.lower()]
print("tables:", cand)
for t in cand:
    for col in ('trade_date', 'end_date', 'nav_date', 'ann_date'):
        try:
            r = c.execute(f"SELECT MAX({col}) FROM {t}").fetchone()
            n = c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=(SELECT MAX({col}) FROM {t})").fetchone()
            print(f"  {t}.{col} max={r[0]} rows_on_max={n[0]}")
        except Exception:
            pass
