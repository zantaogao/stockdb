#!/usr/bin/env python3
"""clf10 概率校准验证（09-21，只读）。
问题：clf10 输出的概率数值本身准不准？
做法：每个成熟信号日，按 clf10 概率切成 10 个分位箱，
每箱算 实际跑赢当日全池中位数 的比例（empirical hit rate），
与箱内预测概率均值对表。判读：对角线=完美校准；看单调性+偏差幅度。
口径：收益=信号日起10交易日 close-to-close（与影子链同），胜出=超过当日截面中位数（与训练标签同定义）。"""
import sqlite3, numpy as np, pandas as pd, duckdb
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

sds = sorted(str(r[0]) for r in tcon.execute("SELECT DISTINCT date FROM shadow_clf10_scores").fetchall())
sds = [s for s in sds if s in pos and pos[s]+FWD < len(all_days)]
frames = []
for sd in sds:
    sc = pd.read_sql_query("SELECT code, score FROM shadow_clf10_scores WHERE date=?", tcon, params=(sd,))
    if len(sc) < 100: continue
    codes = sc['code'].astype(str).tolist()
    p0, p1 = px(sd, codes), px(all_days[pos[sd]+FWD], codes)
    sc['ret'] = [(p1.get(tc(c), np.nan)/p0.get(tc(c), np.nan)-1) for c in codes]
    sc = sc.dropna(subset=['ret','score'])
    if len(sc) < 100: continue
    sc['win'] = (sc['ret'] > sc['ret'].median()).astype(float)  # 当日截面中位=训练标签定义
    sc['sd'] = sd
    frames.append(sc)
d = pd.concat(frames, ignore_index=True)
print(f"样本：{d.sd.nunique()} 个成熟信号日（{d.sd.min()}~{d.sd.max()}），共 {len(d)} 票·日；全局基准命中率≈50%")
d['bin'] = d.groupby('sd')['score'].transform(lambda s: pd.qcut(s.rank(method='first'), 10, labels=False)+1)
tab = d.groupby('bin').agg(n=('win','size'), pred=('score','mean'), actual=('win','mean'))
tab['se'] = np.sqrt(tab.actual*(1-tab.actual)/tab.n)
print(f"\n{'分位箱':<6}{'n':>7}{'预测概率均值':>10}{'实际命中率':>10}{'±2SE':>9}{'偏差':>8}")
for b, r in tab.iterrows():
    flag = '' if abs(r.actual-r.pred) <= 2*r.se else '  ← 超2SE'
    print(f"P{int(b)*10:<5}{int(r.n):>7}{r.pred*100:>9.1f}%{r.actual*100:>9.1f}%{2*r.se*100:>8.1f}%{(r.actual-r.pred)*100:>+7.1f}pp{flag}")
sp = d.groupby('sd').apply(lambda g: (g['score']>0.5).mean(), include_groups=False)
print(f"\n单调性：实际命中率 从P10箱到P100箱 {'升序' if tab.actual.is_monotonic_increasing else '非严格升序'}")
print(f"头部精度：预测≥0.60 的票 实际命中率 {d[d.score>=0.60].win.mean()*100:.1f}% (n={int((d.score>=0.60).sum())})；预测≤0.45 实际 {d[d.score<=0.45].win.mean()*100:.1f}% (n={int((d.score<=0.45).sum())})")
# top10 视角（每日内 clf10 前10名 vs 随机10名的实际命中率）
t10 = d.groupby('sd').apply(lambda g: g.nlargest(10,'score').win.mean(), include_groups=False)
rnd = d.groupby('sd')['win'].mean()
print(f"top10视角：clf10每日前10名平均命中率 {t10.mean()*100:.1f}% vs 池内基准 {rnd.mean()*100:.1f}%（分离度={((t10-rnd).mean())*100:+.1f}pp）")
