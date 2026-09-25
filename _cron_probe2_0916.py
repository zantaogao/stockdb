import duckdb, sqlite3
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for t in ['board_daily','stock_info','stock_daily']:
    cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
    print(f"-- {t} cols:", cols)
    try:
        print(con.execute(f"SELECT * FROM {t} LIMIT 3").fetchall())
        print(con.execute(f"SELECT MAX(trade_date) FROM {t}").fetchone() if 'trade_date' in cols else '')
    except Exception as e:
        print("err", e)
# industry naming
try:
    print("board_daily distinct types:", con.execute("SELECT DISTINCT board_type FROM board_daily LIMIT 20").fetchall())
except Exception as e: print(e)
try:
    print("board_daily name sample:", con.execute("SELECT DISTINCT name FROM board_daily WHERE name LIKE '%半导体%' OR name LIKE '%黄金%' LIMIT 10").fetchall())
except Exception as e: print(e)
con.close()
print("=== archive ===")
import os, glob
arc = sorted(glob.glob(os.path.expanduser('~/.hermes/stockdb/analysis/archive/postmarket_*.txt')))
print(arc[-3:])
