#!/usr/bin/env python3
"""clf10 当融合分门票实测（09-21，只读）。
问题：融合分排序选 top10，但先过 clf10 概率门票（分位≥P），是否更好？
口径：signal_history.fusion_score（0.20reg10+0.30reg20+0.50reg40，不受0921复权修复影响）、
shadow_clf10_scores、收益=信号日起10交易日 close-to-close（与影子链同口径）。
判定：逐日 top10 收益配对差 NW(lag10)。"""
import sqlite3, numpy as np, pandas as pd, duckdb
from scipy import stats
from pathlib import Path
BASE = Path.home()/'.hermes/stockdb'
FWD = 10
tcon = sqlite3.connect(BASE/'signals.db')
dcon = duckdb.connect(str(BASE/'tushare.db'), read_only=True)
all_days = [str(r[0]) for r in dcon.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
pos = {d: i for i, d in enumerate(all_days)}
def tc(c): return f"{c}.SH" if c.startswith(('6','68','9')) else f"{c}.SZ"
def px(d, codes):
    out = {}; arr = [tc(c) for c in codes]
    for k in range(0, len(arr), 900):
        ch = arr[k:k+900]; ph = ','.join(['?']*len(ch))
        for t, c in dcon.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [d]+ch).fetchall():
            out[str(t)] = float(c)
    return out

sds = [str(r[0]) for r in tcon.execute("SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
sds = [s for s in sds if s in pos and pos[s]+FWD < len(all_days)]
rows = []
for sd in sds:
    end = all_days[pos[sd]+FWD]
    sig = pd.read_sql_query("SELECT stock_code code, fusion_score, reg10 FROM signal_history WHERE REPLACE(date,'-','')=?", tcon, params=(sd,)).drop_duplicates('code')
    if len(sig) < 100: continue
    clf = dict(tcon.execute("SELECT code, score FROM shadow_clf10_scores WHERE date=?", (sd.replace('-','') if False else sd,)).fetchall())
    if not clf:
        # 表 date 存 YYYYMMDD
        clf = dict(tcon.execute("SELECT code, score FROM shadow_clf10_scores WHERE date=?", (sd,)).fetchall())
    sig['clf10'] = sig['code'].astype(str).map({str(k): v for k, v in clf.items()})
    codes = sig['code'].astype(str).tolist()
    p0, p1 = px(sd, codes), px(end, codes)
    sig['ret'] = [(p1.get(tc(c), np.nan)/p0.get(tc(c), np.nan)-1) for c in codes]
    d = sig.dropna(subset=['ret','fusion_score','clf10'])
    if len(d) < 100: continue
    r = {'sd': sd}
    base_top = d.nlargest(10, 'fusion_score')
    r['base'] = base_top['ret'].mean()
    # 门票被踢掉的原始top10数量 + 原top10的clf10平均截面分位
    base_pctl = (d['clf10'].rank(pct=True)*100)[d['code'].isin(base_top['code'])]
    r['base_clf_pctl_mean'] = float(base_pctl.mean())
    for P in (50, 70, 90):
        pool = d[d['clf10'] >= np.percentile(d['clf10'], P)]
        tf = pool.nlargest(10, 'fusion_score')
        r[f'p{P}'] = tf['ret'].mean()
        r[f'kick{P}'] = int((~base_top['code'].isin(tf['code'])).sum())
    rows.append(r)
ev = pd.DataFrame(rows)
print(f"成熟信号日 {len(ev)} 天（{ev.sd.min()}~{ev.sd.max()}）")
print(f"融合分top10 的 clf10 截面分位均值：{ev.base_clf_pctl_mean.mean():.1f}（若≈95说明top10本来就全是clf高分票，门票≈空转）")
def nw(dv, tag):
    dv = np.asarray(dv, float); dv = dv[np.isfinite(dv)]; n = len(dv)
    e = dv - dv.mean(); var = float(e@e/n)
    for lag in range(1, 11): var += 2*(1-lag/11)*float(e[lag:]@e[:-lag]/n)
    t = dv.mean()/np.sqrt(var/n); p = 2*(1-stats.norm.cdf(abs(t)))
    print(f"{tag}: 日均差 {dv.mean()*100:+.2f}pp  NW t={t:+.2f} p={p:.4f}  n={n}  过滤日更优 {(dv>0).mean()*100:.0f}%")
print(f"\n基准 融合分纯排序top10: 日均 {ev.base.mean()*100:+.2f}%")
for P in (50, 70, 90):
    print(f"clf10≥P{P}门票后top10: 日均 {ev['p'+str(P)].mean()*100:+.2f}%  平均踢掉原top10中 {ev['kick'+str(P)].mean():.1f} 只")
    nw(ev['p'+str(P)] - ev['base'], f"P{P}门票 - 基准")
