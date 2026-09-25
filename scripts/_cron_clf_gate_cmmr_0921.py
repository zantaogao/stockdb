#!/usr/bin/env python3
"""clf10 给 CMMR 当门票实测（09-21，只读）。
现行 CMMR 选池 = cmmr_score>=80 地板 + fusion_score 次级键 top10（与策略账户同键序）。
测三种 clf10 插法：
  A) cmmr>=80 且 clf10截面分位>=P，池内仍 fusion 排 top10（clf当第二门票）
  B) 80地板内次级键直接换 clf10（clf当排序键，替换fusion）
  C) 对照基准 = 现行
持有窗口按 OPS_FACTS：80+池 alpha 峰值第10天，主判 fwd10，附 fwd20。
收益=信号日起 N 交易日 close-to-close。逐日配对差 NW(lag10/lag20)。"""
import sqlite3, numpy as np, pandas as pd, duckdb
from scipy import stats
from pathlib import Path
BASE = Path.home()/'.hermes/stockdb'
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

sds = [str(r[0]) for r in tcon.execute("SELECT DISTINCT REPLACE(date,'-','') FROM signal_history WHERE cmmr_score IS NOT NULL ORDER BY 1").fetchall()]
sds = [s for s in sds if s in pos and pos[s]+20 < len(all_days)]
rows = []
for sd in sds:
    sig = pd.read_sql_query("SELECT stock_code code, cmmr_score, fusion_score FROM signal_history WHERE REPLACE(date,'-','')=?", tcon, params=(sd,)).drop_duplicates('code')
    clf = {str(k): v for k, v in tcon.execute("SELECT code, score FROM shadow_clf10_scores WHERE date=?", (sd,)).fetchall()}
    sig['clf10'] = sig['code'].astype(str).map(clf)
    codes = sig['code'].astype(str).tolist()
    p0 = px(sd, codes)
    for FWD, TAG in ((10, 'f10'), (20, 'f20')):
        end = all_days[pos[sd]+FWD]
        p1 = px(end, codes)
        d = sig.copy()
        d['ret'] = [(p1.get(tc(c), np.nan)/p0.get(tc(c), np.nan)-1) for c in d['code'].astype(str)]
        d = d.dropna(subset=['ret','cmmr_score']); d['fusion_score'] = d['fusion_score'].fillna(0)
        d = d.sort_values(['cmmr_score','fusion_score'], ascending=False, kind='mergesort')
        if len(d) < 100: continue
        r = {'sd': sd}
        floor = d[d['cmmr_score'] >= 80]
        r['pool_n'] = len(floor)
        base = floor.sort_values(['cmmr_score','fusion_score'], ascending=False, kind='mergesort').head(10)  # 现行账户键序
        r['base_'+TAG] = base['ret'].mean()
        if d['clf10'].notna().sum() >= 100:
            d['clf_pctl'] = d['clf10'].rank(pct=True)*100
            for P in (50, 70):
                pool = floor[floor['code'].isin(d[d['clf_pctl'] >= P]['code'])]
                tf = pool.sort_values(['cmmr_score','fusion_score'], ascending=False, kind='mergesort').head(10)
                r[f'A{P}_'+TAG] = tf['ret'].mean() if len(tf) else np.nan
                r[f'A{P}kick_'+TAG] = int((~base['code'].isin(tf['code'])).sum())
            fl = floor.dropna(subset=['clf10'])
            if len(fl) >= 10:
                alt = fl.nlargest(10, 'clf10')          # B: 地板内 clf10 直接当排序键
                r['B_'+TAG] = alt['ret'].mean()
                r['Bkick_'+TAG] = int((~base['code'].isin(alt['code'])).sum())
        rows.append(r)
ev = pd.DataFrame(rows)
print(f"成熟信号日 {len(ev)} 天（{ev.sd.min()}~{ev.sd.max()}），80+池均规模 {ev.pool_n.mean():.0f} 只")
print(f"基准（现行 cmmr≥80 + fusion次级键 top10）: fwd10 {ev.base_f10.mean()*100:+.2f}%  fwd20 {ev.base_f20.mean()*100:+.2f}%")
def nw(dv, tag, lag):
    dv = np.asarray(dv, float); dv = dv[np.isfinite(dv)]; n = len(dv)
    if n < 5: print(f"{tag}: n={n} 太少"); return
    e = dv - dv.mean(); var = float(e@e/n)
    for l in range(1, lag+1): var += 2*(1-l/(lag+1))*float(e[l:]@e[:-l]/n)
    t = dv.mean()/np.sqrt(var/n); p = 2*(1-stats.norm.cdf(abs(t)))
    print(f"{tag}: 日均差 {dv.mean()*100:+.2f}pp  NW(lag{lag}) t={t:+.2f} p={p:.4f}  n={n}  更优日 {(dv>0).mean()*100:.0f}%")
for P in (50, 70):
    col = f'A{P}_f10'
    if col in ev and ev[col].notna().sum() >= 5:
        print(f"\nA) clf10≥P{P} 第二门票: fwd10 {ev[col].mean()*100:+.2f}%（踢掉原top10均{ev[f'A{P}kick_f10'].mean():.1f}只） fwd20 {ev[f'A{P}_f20'].mean()*100:+.2f}%")
        nw(ev[col]-ev.base_f10, f'  A{P}门票-基准 fwd10', 10)
        nw(ev[f'A{P}_f20']-ev.base_f20, f'  A{P}门票-基准 fwd20', 20)
if 'B_f10' in ev and ev.B_f10.notna().sum() >= 5:
    print(f"\nB) 80地板内 clf10 当排序键: fwd10 {ev.B_f10.mean()*100:+.2f}%（踢掉{ev.Bkick_f10.mean():.1f}只） fwd20 {ev.B_f20.mean()*100:+.2f}%")
    nw(ev.B_f10-ev.base_f10, '  B排序键-基准 fwd10', 10)
    nw(ev.B_f20-ev.base_f20, '  B排序键-基准 fwd20', 20)
