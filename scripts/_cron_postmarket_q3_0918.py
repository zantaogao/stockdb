import duckdb, sqlite3, os, re
H = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{H}/tushare.db', read_only=True)
print('== board_daily cols ==')
print([c[1] for c in t.execute("PRAGMA table_info(board_daily)").fetchall()])
print(t.execute("SELECT * FROM board_daily LIMIT 5").fetchall())
print(t.execute("SELECT MAX(trade_date) FROM board_daily").fetchall())
# 找 sw_daily_raw 在别处
for db in ['~/.hermes/growth.db', '~/.hermes/stockdb/signals.db', '~/.hermes/stockdb/factors.db']:
    p = os.path.expanduser(db)
    if not os.path.exists(p): continue
    try:
        tt = duckdb.connect(p, read_only=True).execute("SHOW TABLES").fetchall()
        names = [x[0] for x in tt]
        print(db, [n for n in names if 'sw' in n or 'industry' in n][:10])
    except Exception as e:
        try:
            c = sqlite3.connect(p)
            names = [x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            print(db, 'sqlite', [n for n in names if 'sw' in n or 'industry' in n][:10])
        except Exception as e2:
            print(db, 'err', e2)
