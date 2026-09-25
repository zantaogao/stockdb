import duckdb, sqlite3, json
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print("== index 5d ==")
for r in con.execute("""SELECT ts_code, trade_date, close, pct_chg FROM index_daily_raw
 WHERE ts_code IN ('000852.SH','000001.SH') AND trade_date>='20260901'
 ORDER BY ts_code, trade_date""").fetchall():
    print(r)
print("== rebalance dates ==")
s = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
for r in s.execute("SELECT account_id, substr(config_json,1,200) FROM strategy_accounts_meta").fetchall():
    print(r)
print("== trading days since 20260901 ==")
print([r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260901' ORDER BY trade_date").fetchall()])
