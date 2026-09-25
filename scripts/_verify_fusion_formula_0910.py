#!/usr/bin/env python3
"""09-10 复核 OPS_FACTS 新口径声称：
fusion_score = round(0.20*reg10 + 0.30*reg20 + 0.50*reg40, 1) 精确式
旧版 25/50/25，切换日 7/31。逐信号日算三种口径(20/30/50, 25/50/25, 70/30近似)的 maxdiff。
注意 reg10 单位=小数，直接线性时贡献≈0 —— 25/50/25 若真匹配，须 reg10×100 化百分点，两种都测。"""
import sqlite3
import pandas as pd

st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
days = [r[0] for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history "
    "WHERE fusion_score IS NOT NULL AND reg10 IS NOT NULL AND reg20 IS NOT NULL AND reg40 IS NOT NULL "
    "ORDER BY 1").fetchall()]
print(f"信号日 {len(days)} 天: {days[0]} ~ {days[-1]}")
print(f"{'日期':<10} {'20/30/50':>9} {'25/50/25':>9} {'25/50/25x100':>13} {'70/30近似':>9}  判定")
for d in days:
    m = pd.read_sql("SELECT reg10,reg20,reg40,fusion_score FROM signal_history WHERE REPLACE(date,'-','')=?",
                    st, params=(d,)).dropna()
    f = m['fusion_score']
    md = lambda pred: float((round(pred,1) - f).abs().max())
    a = md(0.20*m.reg10 + 0.30*m.reg20 + 0.50*m.reg40)
    b = md(0.25*m.reg10 + 0.50*m.reg20 + 0.25*m.reg40)
    c = md(0.25*m.reg10*100 + 0.50*m.reg20 + 0.25*m.reg40)
    e = md(0.30*m.reg20 + 0.70*m.reg40)
    cand = {'精确20/30/50': a, '旧25/50/25': b, '25/50/25×100': c, '近似70/30': e}
    win = min(cand, key=cand.get)
    print(f"{d:<10} {a:>9.2f} {b:>9.2f} {c:>13.2f} {e:>9.2f}  {win}({cand[win]:.2f})")
