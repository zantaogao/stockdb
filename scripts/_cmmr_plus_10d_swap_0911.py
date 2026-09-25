#!/usr/bin/env python3
"""把 CMMR+ 的底座换成纯 10d 对拍（2026-09-11 用户拍板试试）。

现用 fusion_score_cmmr = old_score(三模型融合分百分位,实际≈20d/40d) × MA40趋势4档乘数。
试验组 v8_10d        = reg10 横截面百分位 × 同一趋势乘数（结构一字不动，只换底座）。

对拍（每个成熟信号日，扣当日全市场等权）：
  A. 全截面 20d/10d IC：fusion_score_cmmr（对照）vs v8_10d（试验）vs reg10裸分
  B. 类账户选池 top10 等权超额：
     b1 现行口径 = ≥80地板 + 档内按融合原始分fusion降序（=cmmr账户现状）
     b2 换底座   = ≥80地板 + 档内按 v8_10d 降序（唯一变量=次级键换10d）
     b3 cmmr+账户口径 = fusion_score_cmmr>0 top15%(p85)等权（对照）
     b4 试验cmmr+ = v8_10d>0 top15%(p85)等权
注意单位：signal_history.reg10 为小数口径；百分位排名不受单位影响。
"""
import sqlite3, duckdb, numpy as np
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
HORIZONS = (10, 20)

def ts(c):
    c = str(c)
    return f'{c}.SH' if c.startswith(('6', '68', '9')) else f'{c}.SZ'

def trend_mult(slope):
    s = slope if slope is not None else 0.0
    if s > 0.05: return 1.3
    if s > 0:    return 1.0
    if s > -0.02: return 0.8
    return 0.5

def pct_rank(vals):
    """横截面百分位 0-100（同生产 ranks/n*100 口径）"""
    a = np.asarray(vals, dtype=float)
    order = np.argsort(a)
    ranks = np.empty(len(a))
    ranks[order] = np.arange(1, len(a) + 1)
    return ranks / len(a) * 100.0

def top_pct(items, key, frac=0.15):
    """>0 池取 top15%（p85 阈值口径，同 cmmr+ 账户）"""
    pool = [i for i in items if i[key] > 0]
    if len(pool) < 10:
        return pool
    thr = np.percentile([i[key] for i in pool], (1 - frac) * 100)
    return sorted([i for i in pool if i[key] >= thr], key=lambda i: -i[key])[:10]

state = sqlite3.connect(str(BASE / 'signals.db'))
tushare = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)

dates = [r[0] for r in state.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]

from scipy.stats import spearmanr
rows_out = {h: [] for h in HORIZONS}  # per horizon per date dict

for d in dates:
    for h in HORIZONS:
        td = tushare.execute(
            "SELECT DISTINCT trade_date FROM daily WHERE trade_date > ? ORDER BY trade_date ASC LIMIT ?", (d, h)).fetchall()
        if len(td) < h:
            continue  # 该 horizon 未成熟
        exit_date = td[-1][0]
        rows = state.execute("""
            SELECT stock_code, reg10, ma40_slope, fusion_score_cmmr,
                   COALESCE(fusion_score,0), cmmr_score
            FROM signal_history WHERE REPLACE(date,'-','')=?""", (d,)).fetchall()
        codes = [ts(r[0]) for r in rows]
        ph = ','.join(['?'] * len(codes))
        p0 = dict(tushare.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (d,) + tuple(codes)).fetchall())
        p1 = dict(tushare.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (exit_date,) + tuple(codes)).fetchall())
        m0 = dict(tushare.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (d,)).fetchall())
        m1 = dict(tushare.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (exit_date,)).fetchall())
        mkt_rets = [(m1[k] / m0[k] - 1) * 100 for k in m0 if k in m1 and m0[k] and m0[k] > 0]
        if not mkt_rets:
            continue
        mkt = float(np.mean(mkt_rets))

        items = []
        reg10_list, idx_ok = [], []
        for i, (code, reg10, slope, fscm, fs, cs) in enumerate(rows):
            t = ts(code)
            if t in p0 and t in p1 and p0[t] and p0[t] > 0 and reg10 is not None:
                reg10_list.append(float(reg10))
                idx_ok.append((code, reg10, slope, fscm, fs, cs, t))
        if len(idx_ok) < 100:
            continue
        pct10 = pct_rank(reg10_list)
        recs = []
        for j, (code, reg10, slope, fscm, fs, cs, t) in enumerate(idx_ok):
            v8_10d = pct10[j] * trend_mult(slope)
            recs.append({'code': code, 'cmmr': float(cs or 0),
                         'ret': (p1[t] / p0[t] - 1) * 100 - mkt,
                         'fscm': float(fscm or 0), 'v8_10d': v8_10d,
                         'reg10': float(reg10), 'fs': float(fs)})
        ic_fscm = spearmanr([r['fscm'] for r in recs], [r['ret'] for r in recs])[0]
        ic_10d = spearmanr([r['v8_10d'] for r in recs], [r['ret'] for r in recs])[0]
        ic_raw = spearmanr([r['reg10'] for r in recs], [r['ret'] for r in recs])[0]

        # 选池
        def top10_floor(key):
            pool = [r for r in recs if r['cmmr'] >= 80]
            return sorted(pool, key=lambda r: (-r[key], r['code']))[:10]
        b1 = top10_floor('fs')
        b2 = top10_floor('v8_10d')
        b3 = top_pct(recs, 'fscm')
        b4 = top_pct(recs, 'v8_10d')
        ew = lambda lst: float(np.mean([r['ret'] for r in lst])) if lst else 0.0
        rows_out[h].append({
            'd': d, 'n': len(recs),
            'ic_fscm': ic_fscm, 'ic_10d': ic_10d, 'ic_raw': ic_raw,
            'b1': ew(b1), 'b2': ew(b2), 'b3': ew(b3), 'b4': ew(b4),
            'n_b4': len(b4)})

for h in HORIZONS:
    rs = rows_out[h]
    if not rs:
        print(f"\n=== {h}日持有窗口：无成熟日 ===")
        continue
    print(f"\n=== 持有窗口 {h} 日 | 成熟 {len(rs)} 个信号日 | 超额已扣当日全市场等权 ===")
    print(f"{'信号日':<10}{'IC现行+':<9}{'IC换10d':<9}{'ICreg10裸':<10}{'池:现行':<8}{'池:10d次级':<10}{'cmmr+现行':<9}{'cmmr+10d':<9}")
    for r in rs:
        print(f"{r['d']:<10}{r['ic_fscm']:+.3f}   {r['ic_10d']:+.3f}   {r['ic_raw']:+.4f}    "
              f"{r['b1']:+.2f}%  {r['b2']:+.2f}%    {r['b3']:+.2f}%   {r['b4']:+.2f}%")
    import numpy as _np
    print('-' * 78)
    print(f"{'均值':<10}{_np.mean([r['ic_fscm'] for r in rs]):+.3f}   "
          f"{_np.mean([r['ic_10d'] for r in rs]):+.3f}   "
          f"{_np.mean([r['ic_raw'] for r in rs]):+.4f}    "
          f"{_np.mean([r['b1'] for r in rs]):+.2f}%  {_np.mean([r['b2'] for r in rs]):+.2f}%    "
          f"{_np.mean([r['b3'] for r in rs]):+.2f}%   {_np.mean([r['b4'] for r in rs]):+.2f}%")
    for a, b, label in [('ic_fscm', 'ic_10d', 'IC'), ('b1', 'b2', '80池top10'), ('b3', 'b4', 'cmmr+池')]:
        wins = sum(1 for r in rs if r[b] > r[a])
        print(f"  {label}: 10d版跑赢 {wins}/{len(rs)} 天, 日均差 {_np.mean([r[b]-r[a] for r in rs]):+.3f}")

state.close(); tushare.close()
