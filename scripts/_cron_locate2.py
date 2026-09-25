import sqlite3
for db in ['/Users/zantao/.hermes/ledger.db', '/Users/zantao/.hermes/state.db', '/Users/zantao/.hermes/signals.db']:
    try:
        c = sqlite3.connect(db, timeout=10)
        t = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(db, '->', 'trade_log' in t, t[:10])
        if 'trade_log' in t:
            print('  agent_auto today:', c.execute("SELECT trade_time,direction,code,quantity,amount FROM trade_log WHERE strategy='agent_auto' AND trade_date='2026-09-24' ORDER BY id").fetchall())
    except Exception as e:
        print(db, 'ERR', e)
