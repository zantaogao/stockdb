# -*- coding: utf-8 -*-
"""终验：真调 scan_stock（改后代码本体），对 3 只除权票核对 ma40_slope/pct_chg_10d = 矩阵复权口径；
并确认 signal_agent 全链 import 无损（不写库）"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))
import duckdb
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
from agents.signal_agent import scan_stock

con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
jumps = con.execute("""
  SELECT DISTINCT a.ts_code FROM adj_factor a JOIN adj_factor b USING (ts_code)
  WHERE a.trade_date='20260918' AND a.trade_date > b.trade_date
    AND a.adj_factor != b.adj_factor AND abs(a.adj_factor/b.adj_factor-1) > 0.02
  LIMIT 3
""").df()
print('除权>2%样本:', list(jumps.ts_code))
for ts in jumps.ts_code:
    x = con.execute(f"SELECT d.trade_date, d.close, a.adj_factor FROM daily d LEFT JOIN adj_factor a USING (ts_code,trade_date) WHERE d.ts_code='{ts}' AND d.trade_date<='20260918' ORDER BY d.trade_date").df()
    f_ = x.adj_factor.ffill().fillna(1.0); ca_ = (x.close*f_).ffill()
    m40 = ca_.rolling(40).mean(); m40l = m40.shift(20)
    sl_mat = float((m40.iloc[-1]-m40l.iloc[-1])/m40l.iloc[-1])
    p_mat = float(ca_.iloc[-1]/ca_.iloc[-11]-1)
    code = ts.split('.')[0]
    r = scan_stock({'stock_code': code, 'stock_name': '', 'industry': '', 'board': ''}, target_date='20260918', conn=con)
    if r is None:
        print(f'{ts}: scan_stock 返回 None（数据不足，正常跳过）'); continue
    ds, dp = abs(r['ma40_slope']-sl_mat), abs(r['pct_chg_10d']-p_mat)
    ok = 'PASS' if (ds < 1e-9 and dp < 1e-9) else 'FAIL'
    print(f"{ts}: slope scan={r['ma40_slope']:+.6f} mat={sl_mat:+.6f} | p10 scan={r['pct_chg_10d']*100:+.4f}% mat={p_mat*100:+.4f}% [{ok}]")
con.close()
print('scan_stock 真函数验证完毕')
