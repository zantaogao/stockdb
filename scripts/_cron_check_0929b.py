import sqlite3
for db in ['/Users/zantao/.hermes/stockdb/data/ledger.db','/Users/zantao/.hermes/stockdb/signals.db','/Users/zantao/.hermes/stockdb/strategy_accounts.db','/Users/zantao/.hermes/stockdb/aquant.db']:
    try:
        con=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
        cur=con.cursor()
        tabs=[r[0] for r in cur.execute("select name from sqlite_master where type='table'").fetchall()]
        print('##',db,'tabs:',tabs)
        for t in tabs:
            cols=[c[1] for c in cur.execute(f'PRAGMA table_info("{t}")').fetchall()]
            dcols=[c for c in cols if 'date' in c.lower() or 'day' in c.lower()]
            if not dcols: continue
            dc=dcols[0]
            for v in ('2026-09-29','20260929'):
                try:
                    rows=cur.execute(f'select * from "{t}" where "{dc}"=? limit 15',(v,)).fetchall()
                except Exception: rows=[]
                if rows:
                    print('  ==',t,'==')
                    for r in rows: print('  ',r)
                    break
        con.close()
    except Exception as e:
        print('ERR',db,e)
