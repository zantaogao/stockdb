#!/usr/bin/env python3
"""6 方向深挖: 持仓差异/资金流/涨跌停/extra/三因子组合/量价背离 2026-08-08"""
import sqlite3, duckdb, json
import numpy as np
import pandas as pd
from scipy import stats

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

feat = pd.read_sql("SELECT date, code, open30_ret, tail30_ret, vwap_dev, rv_1m, amp_intra, vol_dist_am FROM tdx_intraday_feat", s)
tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260212' ORDER BY trade_date").fetchall()]
nx = {d: tds[i+1] for i, d in enumerate(tds[:-1])}
def c2t(c): return f"{c}.SH" if str(c).startswith(("6","68","9")) else f"{c}.SZ"
px = {}
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260212'").fetchall():
    px.setdefault(str(d), {})[tc] = float(cl)
rows = []
for _, r in feat.iterrows():
    dd, nxt = str(r['date']), nx.get(str(r['date']))
    tc = c2t(r['code'])
    c0, c1 = (px.get(dd, {}).get(tc), px.get(nxt, {}).get(tc)) if nxt else (None, None)
    ret = (c1/c0-1)*100 if c0 and c1 and c0 > 0 else None
    rows.append((r['date'], r['code'], r['open30_ret'], r['tail30_ret'], r['vwap_dev'], r['rv_1m'], r['amp_intra'], r['vol_dist_am'], ret))
df = pd.DataFrame(rows, columns=['date','code','open30','tail30','vwap','rv1m','amp','voldist','ret'])
df['date_s'] = df['date'].astype(str)
df = df.dropna(subset=['ret'])
print(f"样本: {len(df)} 行\n")

def rep(label, g, base=None):
    if len(g) < 100: print(f"  {label}: n={len(g)} 样本不足"); return
    b = base if base is not None else 0
    print(f"  {label}: n={len(g):>7} 次日均值 {g.mean():>+6.2f}% 中位 {g.median():>+6.2f}% 涨占比 {np.mean(g>0):.1%}")

# ── 方向3: 持仓 vs 非持仓 ──
print("【方向3: 持仓 vs 非持仓 (全期特征)】")
held = {r[0] for r in s.execute("SELECT code FROM holdings WHERE status='hold'").fetchall()}
for col, name in [('tail30','尾盘30分'), ('vwap','VWAP偏离'), ('rv1m','RV_1m'), ('amp','振幅'), ('open30','开盘30分')]:
    h, nh = df[df['code'].isin(held)][col], df[~df['code'].isin(held)][col]
    print(f"  {name}: 持仓均值 {h.mean():+.4f} vs 非持仓 {nh.mean():+.4f} (持仓n={len(h)})")

# ── 方向2: 主力资金流 ──
print("\n【方向2: 主力净流入(main_pct) → 当日尾盘 + 次日】")
mf = t.execute("SELECT stock_code, REPLACE(CAST(date AS VARCHAR),'-','') AS d, main_pct, net_amount FROM money_flow WHERE date >= CAST('2026-02-12' AS DATE)").df()
print(f"  money_flow 样本: {len(mf)}, main_pct 分布: 均值 {mf['main_pct'].mean():.2f} 正占比 {(mf['main_pct']>0).mean():.1%}")
m = df.merge(mf, left_on=['code','date_s'], right_on=['stock_code','d'], how='inner')
print(f"  join 成功: {len(m)} 行")
p25, p75 = m['main_pct'].quantile(0.25), m['main_pct'].quantile(0.75)
rep("主力大幅流入(>P75)", m[m['main_pct']>p75]['ret'])
rep("主力大幅流出(<P25)", m[m['main_pct']<p25]['ret'])
rep("对照(全样本)", df['ret'])
print(f"  大幅流入组当日tail30均值 {m[m['main_pct']>p75]['tail30'].mean():+.4f} vs 流出组 {m[m['main_pct']<p25]['tail30'].mean():+.4f}")

# ── 方向4: 七日涨跌停 ──
print("\n【方向4: 七日涨跌停 up_count → 次日】")
nt = t.execute("SELECT ts_code, REPLACE(trade_date,'-','') AS d, up_count FROM stk_nineturn WHERE trade_date >= '2026-02-12'").df()
nt['code'] = nt['ts_code'].str[:6]
m4 = df.merge(nt[['code','d','up_count']], left_on=['code','date_s'], right_on=['code','d'], how='inner')
print(f"  join 成功: {len(m4)} 行, up_count 分布: {m4['up_count'].value_counts().head(5).to_dict()}")
for label, cond in [('up_count=0', m4['up_count']==0), ('up_count=1', m4['up_count']==1),
                    ('up_count>=2', m4['up_count']>=2), ('up_count>=3', m4['up_count']>=3)]:
    rep(label, m4[cond]['ret'])
print(f"  up_count>=2 当日tail30 {m4[m4['up_count']>=2]['tail30'].mean():+.4f} vs up_count=0 {m4[m4['up_count']==0]['tail30'].mean():+.4f}")

# ── 方向5: stk_factor extra (换手/量比/估值) ──
print("\n【方向5: extra JSON 换手率/量比/PE → 次日】")
ex = t.execute("""
    SELECT ts_code, REPLACE(CAST(trade_date AS VARCHAR),'-','') AS d,
           json_extract_string(extra,'$.turnover_rate') AS tr,
           json_extract_string(extra,'$.volume_ratio') AS vr,
           json_extract_string(extra,'$.pe_ttm') AS pe
    FROM stk_factor WHERE trade_date >= '2026-02-12'
""").df()
ex['code'] = ex['ts_code'].str[:6]
for c in ['tr','vr','pe']:
    ex[c] = pd.to_numeric(ex[c], errors='coerce')
m5 = df.merge(ex[['code','d','tr','vr','pe']], left_on=['code','date_s'], right_on=['code','d'], how='inner')
print(f"  join 成功: {len(m5)} 行")
tr_hi, vr_hi = m5['tr'].quantile(0.9), m5['vr'].quantile(0.9)
pe_lo = m5['pe'].quantile(0.1)
rep("换手率>P90", m5[m5['tr']>tr_hi]['ret'])
rep("量比>P90", m5[m5['vr']>vr_hi]['ret'])
rep("PE_TTM<P10(低估值)", m5[m5['pe']<pe_lo]['ret'])
print(f"  换手>P90 当日tail30 {m5[m5['tr']>tr_hi]['tail30'].mean():+.4f} vs 全样本 {m5['tail30'].mean():+.4f}")

# ── 方向6: 三因子组合 (open30 × vwap × amp) ──
print("\n【方向6: 开盘×VWAP×振幅 8组合 → 次日】")
o_m, v_m, a_m = df['open30'].median(), df['vwap'].median(), df['amp'].median()
combos = [('开涨+VWAP高+振幅中', (df['open30']>o_m)&(df['vwap']>v_m)&(df['amp']<=df['amp'].quantile(0.75))),
          ('开跌+VWAP高+振幅低', (df['open30']<o_m)&(df['vwap']>v_m)&(df['amp']<a_m)),
          ('开涨+VWAP低+振幅大', (df['open30']>o_m)&(df['vwap']<v_m)&(df['amp']>df['amp'].quantile(0.75))),
          ('开跌+VWAP低+振幅小', (df['open30']<o_m)&(df['vwap']<v_m)&(df['amp']<a_m)),
          ('开涨+VWAP高+振幅大', (df['open30']>o_m)&(df['vwap']>v_m)&(df['amp']>df['amp'].quantile(0.75))),
          ('开跌+VWAP高+振幅大', (df['open30']<o_m)&(df['vwap']>v_m)&(df['amp']>df['amp'].quantile(0.75)))]
for label, cond in combos:
    rep(label, df[cond]['ret'])

# ── 方向7: 量价背离 (用 money_flow 净流入做"量") ──
print("\n【方向7: 资金量×尾盘 (money_flow net_amount 做量)】")
m7 = m.copy()
m7['net_pos'] = m7['net_amount'] > 0
for label, cond in [('净流入+尾盘涨(量放价涨)', (m7['net_pos'])&(m7['tail30']>0.005)),
                    ('净流出+尾盘涨(量缩价涨)', (~m7['net_pos'])&(m7['tail30']>0.005)),
                    ('净流入+尾盘跌', (m7['net_pos'])&(m7['tail30']<-0.005)),
                    ('净流出+尾盘跌(恐慌抛售)', (~m7['net_pos'])&(m7['tail30']<-0.005))]:
    rep(label, m7[cond]['ret'])
s.close(); t.close()
