#!/usr/bin/env python3
# 查 ca_calendar 漏报 001225/0923 的根因：adj_factor 表有没有该票该区间数据
import duckdb, sqlite3
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
q1 = "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code='001225.SZ' AND trade_date BETWEEN '20260915' AND '20260924' ORDER BY trade_date"
print('001225 adj_factor 0915-0924:', d.execute(q1).fetchall())
q2 = "SELECT COUNT(*) FROM adj_factor WHERE trade_date='20260923'"
print('0923 adj_factor 全市场行数:', d.execute(q2).fetchone())
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db', timeout=10)
print('ca_calendar 0923 除权条数:', sig.execute("SELECT COUNT(*) FROM ca_calendar WHERE ex_date='20260923'").fetchone())
print('ca_calendar 0921-0924 各日条数:', sig.execute("SELECT ex_date, COUNT(*) FROM ca_calendar WHERE ex_date>='20260915' GROUP BY ex_date ORDER BY ex_date").fetchall())
