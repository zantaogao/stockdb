#!/usr/bin/env python3
"""核查 fund_daily 最新日期与行数（只读，勿写库）"""
import duckdb, sqlite3, json
BASE = "/Users/zantao/.hermes/stockdb"
db = duckdb.connect(f"{BASE}/tushare.db", read_only=True)
mx = db.execute("SELECT MAX(trade_date) FROM fund_daily").fetchone()[0]
n_today = db.execute("SELECT COUNT(*) FROM fund_daily WHERE trade_date='20260929'").fetchone()[0]
recent = db.execute("SELECT trade_date, COUNT(*) FROM fund_daily GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5").fetchall()
# 最近交易日口径
try:
    td = db.execute("SELECT MAX(trade_date) FROM daily WHERE trade_date<='20260929'").fetchone()[0]
except Exception as e:
    td = f"ERR:{e}"
db.close()
print(json.dumps({"max_trade_date": mx, "rows_20260929": n_today, "recent5": recent, "last_trade_date_daily": td}, ensure_ascii=False))
