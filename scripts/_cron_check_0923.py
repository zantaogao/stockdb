import sqlite3, duckdb, os, glob
base = os.path.expanduser('~/.hermes/stockdb')
# find DBs
for name in ['signals.db','ledger.db','factors.db']:
    p = None
    for cand in [os.path.join(base,name), os.path.join(base,'data',name)]:
        if os.path.exists(cand): p=cand; break
    if not p:
        g = glob.glob(base+'/**/'+name, recursive=True)
        p = g[0] if g else None
    print(name, p)
    if p:
        con = sqlite3.connect(p)
        cur = con.cursor()
        tabs = [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]
        print('  tables:', tabs)
        for t in tabs:
            cols = [r[1] for r in cur.execute(f'pragma table_info({t})')]
            dcol = None
            for c in cols:
                if c.lower() in ('date','trade_date','dt','day','signal_date','created_at','ts'):
                    dcol=c; break
            if dcol:
                try:
                    n = cur.execute(f"select count(*) from {t} where {dcol} like '2026-09-23%' or {dcol} like '20260923%'").fetchone()[0]
                    if n: print(f'  {t}: {n} rows on 0923 (col {dcol})')
                except Exception as e:
                    pass
        con.close()
