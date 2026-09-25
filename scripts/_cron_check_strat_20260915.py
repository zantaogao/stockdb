import sqlite3, os, glob, json, datetime

LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(LED)
cur = con.cursor()
tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("TABLES:", tabs)
for t in ('strategy_accounts_meta', 'strategy_positions', 'strategy_trades', 'strategy_nav'):
    if t in tabs:
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})")]
        print(f"\n== {t} cols={cols}")
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"   rows={n}")
        try:
            print("   sample:", cur.execute(f"SELECT * FROM {t} LIMIT 3").fetchall())
        except Exception as e:
            print("   sample err", e)

# NAV per account, last 3 dates
for t in ('strategy_nav', 'strategy_accounts_meta'):
    if t in tabs:
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})")]
        dcol = next((c for c in cols if 'date' in c.lower()), None)
        acol = next((c for c in cols if c.lower() in ('account', 'account_id', 'aid', 'strategy')), None)
        if dcol and acol:
            print(f"\n== {t} per-account latest dates")
            for r in cur.execute(f"SELECT {acol}, MAX({dcol}), COUNT(*) FROM {t} GROUP BY {acol} ORDER BY {acol}"):
                print("   ", r)

print("\n== 20260915 trades if table has date col")
for t in tabs:
    if 'trade' in t.lower() or 'ledger' in t.lower():
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})")]
        dcol = next((c for c in cols if 'date' in c.lower() or 'time' in c.lower()), None)
        if dcol:
            rows = cur.execute(f"SELECT * FROM {t} WHERE REPLACE(CAST({dcol} AS TEXT),'-','') LIKE '20260915%'").fetchall()
            print(f"   {t}({dcol}) today_rows={len(rows)}")
            for r in rows[:20]:
                print("      ", r)
con.close()

print("\n== NAV last records per account (last 3)")
con = sqlite3.connect(LED)
cur = con.cursor()
for f in sorted(glob.glob(os.path.expanduser('~/.hermes/stockdb/sim_accounts/*.json'))):
    if '/main' in f or '.old' in f or '.err' in f:
        continue
    try:
        d = json.load(open(f))
    except Exception as e:
        print(os.path.basename(f), "JSON ERR", e)
        continue
    h = d.get('nav_history') or []
    tail = [(x.get('date'), x.get('nav')) for x in h[-3:]]
    print(f"{os.path.basename(f)} closed={d.get('closed')} name={d.get('name')} positions={len(d.get('positions',[]))} cash={d.get('cash')} nav_tail={tail}")
con.close()
