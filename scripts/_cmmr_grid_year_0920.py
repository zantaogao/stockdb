# -*- coding: utf-8 -*-
"""CMMR 权重网格 · 单年重放（2026-09-20，逐年分开跑版）
用法: python3 _cmmr_grid_year_0920.py 2015
每天×每权重的 top10超额 明细追加写 analysis/cmmr_grid_days/{year}.csv
打分口径逐字复刻生产 cmmr_standalone.py（阶梯+红线），入场次日收盘、持有10交易日、
成本0.1%/边、基准当日全可交易域中位。只加载 年前160交易日~年后15交易日 窗口。
"""
import duckdb, sqlite3, os, sys, time, bisect
import numpy as np, pandas as pd

HOME = os.path.expanduser('~')
DB = f'{HOME}/.hermes/stockdb/tushare.db'
SIG = f'{HOME}/.hermes/stockdb/signals.db'
OUT = f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days'
os.makedirs(OUT, exist_ok=True)
year = int(sys.argv[1])
FWD, COST = 10, 0.002

con = duckdb.connect(DB, read_only=True)
alld = [int(r[0]) for r in con.execute("select distinct trade_date from daily order by 1").fetchall()]
i0 = bisect.bisect_left(alld, year*10000)
i1 = bisect.bisect_left(alld, (year+1)*10000)
if i0 >= i1:
    print(f'{year}: 无交易日'); sys.exit(0)
lo = max(0, i0-160); hi = min(len(alld), i1+15)
d_lo, d_hi = alld[lo], alld[hi-1]

bad = set()
sc = sqlite3.connect(f'file:{SIG}?mode=ro', uri=True)
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8','4','92')):
        bad.add(str(code))
sc.close()

df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) AS td, d."open", d.close, d.vol, a.adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE d.trade_date BETWEEN '{d_lo}' AND '{d_hi}'
""").df()
con.close()
df = df[~df.ts_code.str[:6].isin(bad)]
col_order = sorted(df.ts_code.unique())
def piv(col):
    return df.pivot(index='td', columns='ts_code', values=col).reindex(columns=col_order).astype('float32')
close = piv('close'); opn = piv('open'); vol = piv('vol')
adjf = piv('adj_factor').ffill().fillna(1.0)
A_ff = (close*adjf).ffill().values
cal = np.array(close.index)
C = close.values; O = opn.values
ma40_ = close.rolling(40).mean()
S = ((ma40_ - ma40_.shift(20)) / ma40_.shift(20)).values
P = (close/close.shift(10) - 1).values
R = (vol/vol.rolling(5).mean()).values
enough = (close.rolling(60).count().values >= 60)

T = np.where(S > 0.02, 1.0, np.where(S > 0, 0.5, 0.0)).astype('float32')
Ov = np.where(P < -0.08, 1.0, np.where(P < -0.04, 0.5, 0.0)).astype('float32')
V = np.where((R < 0.8) | ((R > 1.2) & (C > O)), 1.0, 0.0).astype('float32')
T[(S < 0) | ~enough | np.isnan(C)] = 0
Ov[(S < 0) | ~enough | np.isnan(C)] = 0
V[(S < 0) | ~enough | np.isnan(C)] = 0

n_days = len(cal)
y_mask = (cal >= year*10000) & (cal < (year+1)*10000)
# 信号日 i 需 i+1+FWD 在窗口内（尾部15交易日缓冲保证 i1 附近也满足）
sig_i = [i for i in np.where(y_mask)[0] if i >= 60 and i+1+FWD < n_days and enough[i].any() and not np.isnan(C[i+1]).all()]

# 当日全可交易域 fwd 与中位
fwd_all = np.full((n_days, len(col_order)), np.nan, 'float32')
for i in sig_i:
    ent_ok = ~np.isnan(C[i+1])
    f = np.where(ent_ok, A_ff[i+1+FWD]/A_ff[i+1] - 1, np.nan).astype('float32')
    fwd_all[i] = f
uni_fwd = np.nanmedian(fwd_all, axis=1)

WEIGHTS = {}
for w1 in range(0, 101, 10):
    for w2 in range(0, 101-w1, 10):
        WEIGHTS[f'{w1}/{w2}/{100-w1-w2}'] = (w1, w2, 100-w1-w2)

rows = []
for name, w in WEIGHTS.items():
    wt, wo, wv = w; tot = wt+wo+wv
    if tot == 0: continue
    sc_all = (wt*T + wo*Ov + wv*V)/tot
    for i in sig_i:
        pool_idx = np.where(sc_all[i] >= 0.8)[0]
        if len(pool_idx) < 10: continue
        pf = fwd_all[i, pool_idx]
        ok = ~np.isnan(pf)
        ps = sc_all[i, pool_idx][ok]; pp = P[i, pool_idx][ok]; pf = pf[ok]
        if len(ps) < 10 or np.isnan(uni_fwd[i]): continue
        order = np.lexsort((pp, -ps))[:10]
        rows.append((year, str(cal[i]), name, len(pool_idx),
                     float(pf[order].mean()-uni_fwd[i]-COST)))
out = pd.DataFrame(rows, columns=['year','date','w','pool_n','ex'])
out.to_csv(f'{OUT}/{year}.csv', index=False)
print(f'{year}: 信号日{len(sig_i)} 明细行{len(out)} 权重组{len(WEIGHTS)}')
