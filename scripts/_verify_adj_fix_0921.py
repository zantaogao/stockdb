# -*- coding: utf-8 -*-
"""验证 signal_agent 复权修复：抽20260918除权票，用新scan_stock逻辑复算 slope/p10
vs 回测链矩阵值（复权），必须一致；并对比旧raw口径差多少"""
import sys, statistics
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
import duckdb, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)

# 找20260915-18窗口内发生除权（adj_factor跳变）的票
jumps = con.execute("""
  SELECT a.ts_code, a.trade_date, a.adj_factor, b.adj_factor AS prev
  FROM adj_factor a JOIN adj_factor b USING (ts_code)
  WHERE a.trade_date IN ('20260916','20260917','20260918')
    AND a.trade_date > b.trade_date
    AND abs(a.adj_factor/b.adj_factor - 1) > 0.005
    AND a.adj_factor != b.adj_factor
  QUALIFY row_number() OVER (PARTITION BY a.ts_code ORDER BY a.trade_date DESC) = 1
  LIMIT 8
""").df()
print('除权票样本:', len(jumps))

def new_logic(ts, target='20260918'):
    rows = con.execute(f"""
        SELECT d.trade_date, d.close, d.open, d.high, d.low, d.pct_chg, d.vol, d.amount, a.adj_factor
        FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
        WHERE d.ts_code = '{ts}' AND d.trade_date <= '{target}'
        ORDER BY d.trade_date DESC LIMIT 200
    """).fetchall()
    if len(rows) < 60: return None
    closes_sorted = [float(r[1]) for r in rows][::-1]
    adj_sorted = []; _f = None
    for r in reversed(rows):
        if r[8] is not None: _f = float(r[8])
        adj_sorted.append(_f)
    _bf = None
    for k in range(len(adj_sorted)-1, -1, -1):
        if adj_sorted[k] is None: adj_sorted[k] = _bf if _bf is not None else 1.0
        else: _bf = adj_sorted[k]
    _base = adj_sorted[-1] or 1.0
    ca = [c*(f/_base) for c, f in zip(closes_sorted, adj_sorted)]
    m40 = statistics.mean(ca[-40:]); m40l = statistics.mean(ca[-60:-20])
    slope = (m40-m40l)/m40l
    p10 = (ca[-1]-ca[-11])/ca[-11]
    # 旧raw口径
    m40r = statistics.mean(closes_sorted[-40:]); m40lr = statistics.mean(closes_sorted[-60:-20])
    sl_r = (m40r-m40lr)/m40lr
    p10r = (closes_sorted[-1]-closes_sorted[-11])/closes_sorted[-11]
    return slope, p10, sl_r, p10r

def grade(s): return 40 if s>0.02 else (20 if s>0 else 0)
def ograde(p): return 40 if p<-0.08 else (20 if p<-0.04 else 0)

nmatch = ndiff = 0
for ts in jumps.ts_code:
    r = new_logic(ts)
    if r is None: continue
    sl_new, p_new, sl_raw, p_raw = r
    gt_new, gt_raw = grade(sl_new)+ograde(p_new), grade(sl_raw)+ograde(p_raw)
    tag = '档位翻!' if gt_new != gt_raw else '同档'
    if gt_new != gt_raw: ndiff += 1
    else: nmatch += 1
    print(f'{ts}: slope adj={sl_new:+.4f} raw={sl_raw:+.4f} | p10 adj={p_new*100:+.2f}% raw={p_raw*100:+.2f}% | 分 new={gt_new} old={gt_raw} {tag}')
print(f'修复后 vs 旧口径档位改变票数: {ndiff}/{nmatch+ndiff}')

# 与回测链矩阵一致性：矩阵复权slope vs 新逻辑（同票同日）
ts = jumps.ts_code.iloc[0]
x = con.execute(f"SELECT d.trade_date, d.close, a.adj_factor FROM daily d LEFT JOIN adj_factor a USING (ts_code,trade_date) WHERE d.ts_code='{ts}' AND d.trade_date<='20260918' ORDER BY d.trade_date").df()
f_ = x.adj_factor.ffill().fillna(1.0).values
ca_ = (x.close*f_).ffill()
m40 = ca_.rolling(40).mean(); m40l = m40.shift(20)
sl_mat = (m40.iloc[-1]-m40l.iloc[-1])/m40l.iloc[-1]
p_mat = ca_.iloc[-1]/ca_.iloc[-11]-1
r = new_logic(ts)
print(f'\n矩阵链 vs 新scan_stock逻辑 ({ts}): slope {sl_mat:+.6f} vs {r[0]:+.6f} (diff {abs(sl_mat-r[0]):.2e}) | p10 {p_mat*100:+.4f} vs {r[1]*100:+.4f}')
con.close()
