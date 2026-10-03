import sqlite3, os
for db in ['state.db','ledger.db']:
    p=os.path.expanduser(f'~/.hermes/stockdb/{db}')
    if not os.path.exists(p): continue
    con=sqlite3.connect(p)
    try:
        tabs=[t[0] for t in con.execute("select name from sqlite_master where type='table'")]
        nav_tabs=[t for t in tabs if 'nav' in t.lower() or 'strategy' in t.lower()]
        print(db, 'nav/strategy tabs:', nav_tabs)
        for t in nav_tabs:
            cols=[c[1] for c in con.execute(f'pragma table_info({t})')]
            if 'date' in cols and any('account' in c for c in cols):
                ac=[c for c in cols if 'account' in c][0]
                rows=con.execute(f'select {ac}, max(date) from {t} group by {ac}').fetchall()
                print(' ', t, rows)
    except Exception as e:
        print(db,'err',e)
    con.close()
