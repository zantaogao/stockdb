import sqlite3, duckdb, os
base = os.path.expanduser("~/.hermes/stockdb")
c = sqlite3.connect(os.path.join(base, "ledger.db"))
print("=== 今日流水(strategy非空) ===")
for r in c.execute("SELECT trade_date,trade_time,strategy,code,name,direction,quantity,price,notes FROM trade_log WHERE REPLACE(trade_date,'-','')='20260915' ORDER BY trade_time"):
    print(r)
print("=== 近3日各策略买卖笔数 ===")
for r in c.execute("SELECT REPLACE(trade_date,'-','') d, strategy, direction, COUNT(*) FROM trade_log WHERE REPLACE(trade_date,'-','')>='20260911' GROUP BY d,strategy,direction ORDER BY d DESC"):
    print(r)

d = duckdb.connect(os.path.join(base, "tushare.db"), read_only=True)
print("=== index_daily 列 ===")
print([r[0] for r in d.execute("PRAGMA table_info('index_daily')").fetchall()])
for code in ("000852.SH", "000001.SH"):
    rows = d.execute("SELECT trade_date, close, pct_chg FROM index_daily WHERE index_code=? ORDER BY trade_date DESC LIMIT 3", [code]).fetchall()
    print(code, rows)

print("=== 中证1000 今日实时(若盘中数据源) ===")
try:
    rows = d.execute("SELECT trade_date, close, pct_chg FROM index_daily_raw WHERE index_code='000852.SH' ORDER BY trade_date DESC LIMIT 3").fetchall()
    print(rows)
except Exception as e:
    print("raw ERR", e)
