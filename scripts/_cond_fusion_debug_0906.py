#!/usr/bin/env python3
import sqlite3, sys
import pandas as pd
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.db import TUSHARE_DB_PATH, _safe_connect
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print("date格式样例:", st.execute("select distinct date from signal_history order by date desc limit 3").fetchall())
con = _safe_connect(TUSHARE_DB_PATH, read_only=True)
print("daily trade_date样例:", con.execute("select trade_date, typeof(trade_date) from daily order by trade_date desc limit 3").fetchall())
d = '20260828'
df = pd.read_sql("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE date=?", st, params=(d[:4]+'-'+d[4:6]+'-'+d[6:],))
print("信号行数", len(df))
print("该日价格:", con.execute("select count(*) from daily where trade_date=?", (d,)).fetchone())
nxt = con.execute("select min(trade_date) from daily where trade_date>?", (d,)).fetchone()
print("次日:", nxt)
con.close(); st.close()