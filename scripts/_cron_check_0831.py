import sqlite3, glob, json, os

DBDIR = os.path.expanduser('~/.hermes/stockdb')
for db in ['ledger.db', 'signals.db']:
    p = os.path.join(DBDIR, db)
    con = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print('==', db, tabs)
    for t in tabs:
        if any(k in t for k in ('trade', 'order', 'pending', 'strategy_positions', 'strategy_accounts')):
            cols = [c[1] for c in con.execute(f'PRAGMA table_info({t})')]
            dcol = None
            for cand in ('date', 'trade_date', 'buy_date', 'sell_date', 'updated_at'):
                if cand in cols:
                    dcol = cand
                    break
            print('--', t, cols, 'dcol=', dcol)
            if dcol:
                rows = con.execute(
                    f"SELECT * FROM {t} WHERE replace({dcol},'-','') LIKE '2026083%' ORDER BY rowid DESC LIMIT 15"
                ).fetchall()
                for r in rows:
                    print(r)
# pending.json
pj = os.path.expanduser('~/.hermes/stockdb/execution/pending.json')
if os.path.exists(pj):
    print('== pending.json', open(pj).read()[:800])
# recent logs
logs = sorted(glob.glob(os.path.expanduser('~/.hermes/stockdb/logs/*strategy*')) +
              glob.glob(os.path.expanduser('~/.hermes/stockdb/logs/*daily*')), key=os.path.getmtime)[-3:]
for lg in logs:
    print('== log', lg)
    print(open(lg, errors='replace').read()[-1500:])