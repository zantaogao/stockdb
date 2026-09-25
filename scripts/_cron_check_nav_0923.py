import sqlite3, os
base = os.path.expanduser('~/.hermes/stockdb')
for rel in ['ledger.db', 'signals.db', 'factors.db']:
    p = os.path.join(base, rel)
    if not os.path.exists(p):
        print(rel, 'MISSING'); continue
    with open(p, 'rb') as f:
        head = f.read(16)
    if b'SQLite' not in head:
        print(rel, 'not-sqlite head=', head[:8]); continue
    con = sqlite3.connect(p)
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    hits = [t for t in tabs if 'nav' in t.lower() or 'strategy' in t.lower() or 'account' in t.lower()]
    print('==', rel, hits)
    for t in hits:
        cols = [c[1] for c in con.execute('PRAGMA table_info(%s)' % t)]
        dcol = None
        for c in ('trade_date', 'date', 'd'):
            if c in cols: dcol = c; break
        key = None
        for c in cols:
            if c in ('account', 'strategy', 'account_id', 'name', 'strat'): key = c; break
        if key is None: key = cols[0]
        try:
            rows = list(con.execute('SELECT %s, MAX(%s), COUNT(*) FROM %s GROUP BY 1 ORDER BY 2 DESC LIMIT 12' % (key, dcol, t)))
            print('  table', t, 'cols', cols)
            for r in rows: print('   ', r)
        except Exception as e:
            print('  table', t, 'ERR', e)
    con.close()
