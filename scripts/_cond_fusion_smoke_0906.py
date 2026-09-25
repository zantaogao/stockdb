#!/usr/bin/env python3
"""09-06 盘前冒烟：数据可用性盘点（reg分/次日收益/中证1000波动代理）。"""
import sqlite3, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.db import TUSHARE_DB_PATH, _safe_connect

con = _safe_connect(TUSHARE_DB_PATH, read_only=True)
tabs = [t[0] for t in con.execute("show tables").fetchall()]
print("index类表:", [t for t in tabs if 'index' in t.lower()])
for t in tabs:
    if 'index' in t.lower():
        cols = [c[0] for c in con.execute(f'describe "{t}"').fetchall()]
        print(t, "cols:", cols[:8])
        try:
            r = con.execute(f'select min(trade_date),max(trade_date),count(*) from "{t}" where ts_code=\'000852.SH\'').fetchone()
            print("  000852.SH:", r)
        except Exception as e:
            print("  000852 err:", e)
con.close()

st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
r = st.execute("select count(distinct date), min(date), max(date) from signal_history where reg10 is not null and reg20 is not null and reg40 is not null and fusion_score is not null").fetchone()
print("signal_history 完整评分日:", r)
st.close()