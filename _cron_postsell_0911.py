import sqlite3, duckdb
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
sells = c.execute("SELECT trade_date,code,name,price FROM trade_log WHERE strategy='agent_auto' AND direction='SELL' AND trade_date>='2026-09-05' ORDER BY trade_date").fetchall()
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print("sell px -> close on sell day / next day(s):")
for sd, code, name, px in sells:
    ts = code + ('.SH' if code.startswith('6') else '.SZ')
    rows = d.execute("SELECT trade_date, pct_chg FROM daily WHERE ts_code=? AND trade_date>? ORDER BY trade_date LIMIT 3", [ts, sd.replace('-','')]).fetchall()
    # pct_chg of days AFTER sell: cumulative move if we had held
    cum = 1.0
    for _, pc in rows: cum *= (1 + pc/100)
    print(sd, code, name, "sellpx", px, "| after-sell pct_chg seq:", [(r[0][4:], r[1]) for r in rows], "| cum %:", round((cum-1)*100, 2))
# market context
print("\nCSI1000 weekly:")
for r in d.execute("SELECT trade_date, pct_chg FROM index_daily WHERE ts_code='000852.SH' AND trade_date>='20260904' ORDER BY trade_date").fetchall():
    print(r)
