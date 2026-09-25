import sqlite3, shutil, os, tempfile, statistics as st
import duckdb

# 市场环境: 近12交易日全市场日均涨幅+涨占比
tj = duckdb.connect("/Users/zantao/.hermes/stockdb/tushare.db", read_only=True)
rows = tj.execute("""
  SELECT trade_date, AVG(pct_chg), 100.0*SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END)/COUNT(*), COUNT(*)
  FROM daily WHERE trade_date >= '20260820' GROUP BY trade_date ORDER BY trade_date
""").fetchall()
print("日期       日均涨幅  涨占比   家数")
for r in rows:
    print(f"{r[0]}  {r[1]:+.2f}%  {r[2]:.0f}%  {r[3]}")

sig = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro", uri=True)
ics = sig.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()[::-1]
print("\n近20哨兵日: 正IC天数占比 fusion/reg10/reg20/reg40:")
cols = list(zip(*[r[1:] for r in ics]))
for name, c in zip(("fusion","reg10","reg20","reg40"), cols):
    pos = sum(1 for v in c if v and v > 0)
    half = len(c)//2
    print(f"{name}: 均值{st.mean(c):+.4f} 正{pos}/{len(c)} 前半{st.mean(c[:half]):+.4f} 后半{st.mean(c[half:]):+.4f}")

# 真窗口 ic_window 最新
try:
    w = sig.execute("SELECT MAX(signal_date) FROM ic_window").fetchone()[0]
    print("\nic_window 最新信号日:", w, "(w10到期回填中)")
except Exception as e:
    print("ic_window ERR", e)