#!/usr/bin/env python3
"""10D + clf10 — 逐日明细核验（防离群值污染）+ 最新名单（--list-only 跳过评估）"""
import sys, sqlite3
import numpy as np, pandas as pd
from pathlib import Path
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
FWD = 10
args = [a for a in sys.argv[1:] if not a.startswith('--')]
LIST_ONLY = '--list-only' in sys.argv
TARGET = args[0] if args else None
tcon = sqlite3.connect(BASE / 'signals.db')
dcon = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
all_days = [str(r[0]) for r in dcon.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
pos = {d: i for i, d in enumerate(all_days)}

def tc(c): return f"{c}.SH" if c.startswith(('6','68','9')) else f"{c}.SZ"
def leg(tab, sd):
    if tab == 'reg10':
        rows = tcon.execute("SELECT stock_code, reg10 FROM signal_history WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    else:
        rows = tcon.execute(f"SELECT code, score FROM {tab} WHERE date=?", (sd,)).fetchall()
    return {str(c): (float(s) if s is not None else np.nan) for c, s in rows}
def px(d, codes):
    out = {}; arr = [tc(c) for c in codes]
    for k in range(0, len(arr), 900):
        ch = arr[k:k+900]; ph = ','.join(['?']*len(ch))
        for t, c in dcon.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [d]+ch).fetchall():
            out[str(t)] = float(c)
    return out

if not LIST_ONLY:
    sds = [str(r[0]) for r in tcon.execute("SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
    sds = [s for s in sds if s in pos and pos[s]+FWD < len(all_days)]
    print(f"逐日明细（reg10 10D腿）：{'信号日':<10}{'基准+10日':<12}{'纯排序top10':>12}{'clf10≥P70后top10':>18}{'全池等权':>10}")
    rows = []
    for sd in sds:
        end = all_days[pos[sd]+FWD]
        r10 = leg('reg10', sd); codes = list(r10.keys())
        if len(codes) < 100: continue
        p0, p1 = px(sd, codes), px(end, codes)
        df = pd.DataFrame({'code': codes})
        df['ret'] = [(p1.get(tc(c), np.nan)/p0.get(tc(c), np.nan)-1) for c in df['code']]
        df['reg10'] = df['code'].map(r10); df['clf10'] = df['code'].map(leg('shadow_clf10_scores', sd))
        d = df.dropna(subset=['ret','clf10','reg10'])
        if len(d) < 100: continue
        top = d.nlargest(10, 'reg10')
        pool = d[d['clf10'] >= np.percentile(d['clf10'], 70)]
        tf = pool.nlargest(10, 'reg10')
        rows.append({'sd': sd, 'base': top['ret'].mean(), 'filt': tf['ret'].mean(),
                     'ew': d['ret'].mean(), 'base_med': top['ret'].median(), 'filt_med': tf['ret'].median(),
                     'base_max': top['ret'].max(), 'base_min': top['ret'].min(),
                     'base_codes': ','.join(top['code'].tolist())})
        print(f"{sd:<14}{end:<12}{top['ret'].mean()*100:>11.2f}%{tf['ret'].mean()*100:>17.2f}%{d['ret'].mean()*100:>9.2f}%")
    ev = pd.DataFrame(rows)
    print("\n== 汇总（28 天）==")
    print(f"纯排序: 均值 {ev['base'].mean()*100:+.2f}%  中位 {ev['base'].median()*100:+.2f}%  "
          f"截尾(去最高2/最低2)后 {ev['base'].sort_values().iloc[2:-2].mean()*100:+.2f}%")
    print(f"P70过滤: 均值 {ev['filt'].mean()*100:+.2f}%  中位 {ev['filt'].median()*100:+.2f}%  "
          f"截尾后 {ev['filt'].sort_values().iloc[2:-2].mean()*100:+.2f}%")
    print(f"全池等权: 均值 {ev['ew'].mean()*100:+.2f}%")
    print(f"\n基准 vs 过滤 逐日：过滤更低 {(ev['filt']<ev['base']).sum()}/{len(ev)} 天；"
          f"中位数口径 基准{ev['base_med'].median()*100:+.2f}% vs 过滤{ev['filt_med'].median()*100:+.2f}%")
    print(f"单日最高 {ev['base'].max()*100:+.1f}%（{ev.loc[ev['base'].idxmax(),'sd']}）"
          f" 单日最低 {ev['base'].min()*100:+.1f}%（{ev.loc[ev['base'].idxmin(),'sd']}）")
    ev.to_csv('/tmp/clf10_daily_eval.csv', index=False)
    print("逐日明细已存 /tmp/clf10_daily_eval.csv")

TGT = TARGET or str(tcon.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0])
print(f"\n==== 名单：信号日 {TGT} ====")
meta = pd.read_sql_query("SELECT stock_code AS code, stock_name, industry FROM signal_history WHERE REPLACE(date,'-','')=?",
                         tcon, params=(TGT,)).drop_duplicates('code')
meta['code'] = meta['code'].astype(str)
meta['reg10'] = meta['code'].map(leg('reg10', TGT))
meta['v4big'] = meta['code'].map(leg('shadow_v4big_scores', TGT))
meta['v4d'] = meta['code'].map(leg('shadow_v4d_scores', TGT))
meta['clf10'] = meta['code'].map(leg('shadow_clf10_scores', TGT))
cl = dcon.execute(
    f"SELECT ts_code, trade_date, close FROM daily WHERE trade_date IN "
    f"(SELECT trade_date FROM (SELECT DISTINCT trade_date FROM daily WHERE trade_date<='{TGT}' ORDER BY trade_date DESC LIMIT 21)) "
    f"AND ts_code IN ({','.join([repr(tc(c)) for c in meta['code']])})").fetchdf()
piv = cl.pivot_table(index='ts_code', columns='trade_date', values='close')
meta['px'] = [piv.iloc[:, -1].get(tc(c), np.nan) for c in meta['code']]
meta['ret20'] = [piv.iloc[:,-1].get(tc(c), np.nan)/piv.iloc[:,0].get(tc(c), np.nan)-1 for c in meta['code']]
meta['q'] = meta['clf10'].rank(pct=True)*100

def show(sel, title):
    d = sel.head(10).copy(); d.insert(0, '#', range(1, len(d)+1))
    cols = ['#','code','stock_name','industry','reg10','v4big','v4d','clf10','q','px','ret20']
    print(f"\n【{title}】"); print(d[cols].round(4).to_string(index=False))

pool70 = meta[meta['q'] >= 70]
show(meta.nlargest(10, 'v4big'), 'A 10D影子v4big 纯排序 top10')
show(pool70.nlargest(10, 'v4big'), f'B v4big 排序 + clf10≥分位70 过滤 top10（池 {len(pool70)}）')
show(meta.nlargest(50, 'v4big').nlargest(10, 'clf10'), 'C v4big 前50池 → clf10 挑 10')
show(meta.nlargest(10, 'reg10'), 'D 生产10D(reg10) 纯排序 top10')
show(pool70.nlargest(10, 'reg10'), 'E 生产10D(reg10) + clf10≥分位70 过滤 top10')
show(meta.nlargest(50, 'reg10').nlargest(10, 'clf10'), 'F 生产10D 前50池 → clf10 挑 10')
show(meta.nlargest(10, 'clf10'), 'G clf10 纯概率 top10')
print(f"\nclf10 {TGT}: min {meta['clf10'].min():.3f} 中位 {meta['clf10'].median():.3f} "
      f"P70 {np.percentile(meta['clf10'].dropna(),70):.3f} P80 {np.percentile(meta['clf10'].dropna(),80):.3f} max {meta['clf10'].max():.3f}")
print(f"覆盖：reg10 {meta['reg10'].notna().sum()} 只 / v4big {meta['v4big'].notna().sum()} / v4d {meta['v4d'].notna().sum()} / clf10 {meta['clf10'].notna().sum()}（全市场 {len(meta)}）")
