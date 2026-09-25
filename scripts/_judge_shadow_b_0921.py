#!/usr/bin/env python3
"""影子B 30成熟日终裁（09-21）：(ic_shadow_b - ic_reg10) 配对 NW(lag10)。只读。
标准：成熟日>=30 且 NW p<0.05 且 均值>0 才议换产。"""
import sqlite3, numpy as np
from scipy import stats as st
BASE = '/Users/zantao/.hermes/stockdb'
NW_LAG = 10
tcon = sqlite3.connect(f'{BASE}/signals.db')
rows = tcon.execute("SELECT signal_date,ic_shadow_b,ic_reg10 FROM ic_shadow WHERE ic_shadow_b IS NOT NULL ORDER BY signal_date").fetchall()
import pandas as pd
hist = pd.DataFrame(rows, columns=['signal_date','ic_shadow_b','ic_reg10'])
d = (hist['ic_shadow_b'] - hist['ic_reg10']).to_numpy()
n = len(d)
mean = d.mean()
# Newey-West
g = d - mean
s = float(g @ g) / n
for lag in range(1, NW_LAG + 1):
    w = 1 - lag / (NW_LAG + 1)
    s += 2 * w * (float(g[lag:] @ g[:-lag]) / n)
se = np.sqrt(s / n)
t_nw = mean / se
p = 2 * (1 - st.t.cdf(abs(t_nw), n - 1))
print(f"B-reg10 配对: n={n} 均值差={mean:+.4f} B均值={hist['ic_shadow_b'].mean():+.4f} reg10均值={hist['ic_reg10'].mean():+.4f} NW(lag{NW_LAG}) t={t_nw:+.2f} p={p:.4f}")
verdict = "达标→议换产" if (n >= 30 and p < 0.05 and mean > 0) else "不达标→退役"
print("终裁:", verdict)
