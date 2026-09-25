#!/usr/bin/env python3
"""8月 CMMR / CMMR+ 信号多维统计（只读）"""
import duckdb, pandas as pd, numpy as np

con = duckdb.connect('tushare.db', read_only=True)
con.execute("ATTACH 'signals.db' AS sig (TYPE sqlite, READ_ONLY)")
con.execute("ATTACH 'ledger.db' AS led (TYPE sqlite, READ_ONLY)")
pd.set_option('display.width', 220); pd.set_option('display.max_columns', 60)

sig = con.execute("""
SELECT REPLACE(date,'-','') AS d, REPLACE(REPLACE(stock_code,'.SZ',''),'.SH','') AS code,
       stock_name AS "name", industry, cmmr_score cmmr, fusion_score_cmmr cmmrp, final_score
FROM sig.signal_history WHERE REPLACE(date,'-','') BETWEEN '20260801' AND '20260831'
""").df()
dates = sorted(sig['d'].unique())

# 行情：全部8月出现过的票，收盘+pct_chg pivot
dl = con.execute("""
SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') code, trade_date d, close, pct_chg
FROM daily WHERE trade_date BETWEEN '20260701' AND '20260930'
""").df()
cal = sorted(dl['d'].unique())
closes = dl.pivot(index='code', columns='d', values='close')
pcts   = dl.pivot(index='code', columns='d', values='pct_chg') / 100.0
mkt = pcts.mean(axis=0) * 100   # 全市场等权日收益%

# 前向收益矩阵（信号日d收盘 -> d+h收盘）
fwd = {}
for h in (3, 5, 10):
    f = (closes.shift(-h) / closes - 1) * 100
    fwd[h] = f
# 市场累计超额基准
mktcum = (1 + mkt/100).cumprod()
mktfwd = {}
for h in (3, 5, 10):
    i = pd.Series(range(len(cal)), index=cal)
    mktfwd[h] = (mktcum.shift(-h) / mktcum - 1) * 100

def attach_fwd(df):
    for h in (3, 5, 10):
        df[f'fwd{h}'] = df.apply(lambda r: fwd[h].at[r['code'], r['d']] if r['code'] in fwd[h].index and r['d'] in fwd[h].columns else np.nan, axis=1)
        df[f'exc{h}'] = df[f'fwd{h}'] - df['d'].map(mktfwd[h])
    return df

# 市值
db_ = con.execute("""
SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') code, REPLACE(trade_date,'-','') d, circ_mv
FROM daily_basic WHERE trade_date BETWEEN '20260801' AND '20260831'
""").df()
mv = db_.pivot(index='code', columns='d', values='circ_mv')
sig['mv_yi'] = sig.apply(lambda r: mv.at[r['code'], r['d']]/1e4 if r['code'] in mv.index and r['d'] in mv.columns else np.nan, axis=1)
sig['board'] = sig['code'].str[:3].map(lambda c: '科创板' if c.startswith('688') else ('创业板' if c.startswith(('300','301')) else '主板'))
sig['dow'] = pd.to_datetime(sig['d'], format='%Y%m%d').dt.day_name()
sig['wk'] = sig['d'].map(lambda d: 'W1(8/3-7)' if d<='20260807' else 'W2(8/10-14)' if d<='20260814' else 'W3(8/17-21)' if d<='20260821' else 'W4(8/24-28)')
sig['day_mkt'] = sig['d'].map(mkt).round(2)

top_c  = sig.sort_values('cmmr', ascending=False).groupby('d').head(10).copy()
top_cp = sig.sort_values('cmmrp', ascending=False).groupby('d').head(10).copy()
top_c = attach_fwd(top_c); top_cp = attach_fwd(top_cp)

print("=== 1. 市场背景（全市场等权日收益%）===")
print({d: round(mkt[d],2) for d in dates})

print("\n=== 2. Top10 前向收益对比（8月全部信号日）===")
for nm, t in [('CMMR ', top_c), ('CMMR+', top_cp)]:
    line = nm
    for h in (3, 5, 10):
        s = t[f'fwd{h}'].dropna(); e = t[f'exc{h}'].dropna()
        line += f" | f{h}: {s.mean():+.2f}%/超{e.mean():+.2f}%/胜率{(s>0).mean()*100:.0f}%/超胜率{(e>0).mean()*100:.0f}%"
    print(line)

print("\n=== 3. 分周对比（Top10 fwd5超额%）===")
for nm, t in [('CMMR ', top_c), ('CMMR+', top_cp)]:
    g = t.dropna(subset=['exc5']).groupby('wk')['exc5'].agg(['mean','count', lambda s:(s>0).mean()*100])
    g.columns = ['exc5均值','n','超胜率%']
    print(nm); print(g.round(2).to_string())

print("\n=== 4. 分数分段单调性（全样本，cmmrp分段，fwd10超额）===")
s2 = sig.sample(min(6000, len(sig)), random_state=7).copy()
s2 = attach_fwd(s2)
s2['bucket'] = pd.cut(s2['cmmrp'], [-1,20,40,60,80,100,200])
print(s2.groupby('bucket', observed=True).agg(n=('exc10','size'), fwd10=('fwd10','mean'), exc10=('exc10','mean'), 胜率=('fwd10', lambda x:(x>0).mean()*100)).round(2).to_string())
s2['bucket2'] = pd.cut(s2['cmmr'], [-1,20,40,60,80,100])
print("cmmr分段:")
print(s2.groupby('bucket2', observed=True).agg(n=('exc10','size'), fwd10=('fwd10','mean'), exc10=('exc10','mean'), 胜率=('fwd10', lambda x:(x>0).mean()*100)).round(2).to_string())

print("\n=== 5. Top10 板块/市值特征 ===")
for nm, t in [('CMMR ', top_c), ('CMMR+', top_cp)]:
    print(nm, "板块:", t['board'].value_counts().to_dict(), " 中位市值(亿):", round(t['mv_yi'].median(),1))
    print("   市值分位: <30亿", (t['mv_yi']<30).sum(), " 30-100亿", ((t['mv_yi']>=30)&(t['mv_yi']<100)).sum(), " 100-300亿", ((t['mv_yi']>=100)&(t['mv_yi']<300)).sum(), " >300亿", (t['mv_yi']>=300).sum())

print("\n=== 6. 行业维度（两策略合并Top10，exc5均值，n>=4）===")
both = pd.concat([top_c.assign(strat='cmmr'), top_cp.assign(strat='cmmrp')])
g = both.dropna(subset=['exc5']).groupby('industry').agg(n=('exc5','size'), exc5=('exc5','mean'), cmmr_n=('strat', lambda s:(s=='cmmr').sum()), cp_n=('strat', lambda s:(s=='cmmrp').sum()))
print(g[g['n']>=4].sort_values('exc5', ascending=False).round(2).to_string())

print("\n=== 7. 星期效应（Top10信号日星期 vs exc5）===")
g = both.dropna(subset=['exc5']).groupby('dow').agg(n=('exc5','size'), exc5=('exc5','mean'), 超胜率=('exc5', lambda s:(s>0).mean()*100))
order = ['Monday','Tuesday','Wednesday','Thursday','Friday']
print(g.reindex(order).round(2).to_string())

print("\n=== 8. 市场环境依赖（信号日大盘涨跌 vs Top10 exc5）===")
both['up'] = both['day_mkt'] > 0
g = both.dropna(subset=['exc5']).groupby('up').agg(n=('exc5','size'), exc5=('exc5','mean'), 超胜率=('exc5', lambda s:(s>0).mean()*100))
print(g.round(2).to_string())
print("按策略x环境 exc5:")
print(both.dropna(subset=['exc5']).groupby(['strat','up'])['exc5'].agg(['count','mean']).round(2).to_string())

print("\n=== 9. 重复上榜票（同票8月进Top10≥3次）表现 vs 单次上榜 ===")
for nm, t in [('CMMR ', top_c), ('CMMR+', top_cp)]:
    cnt = t.groupby('code').size()
    t2 = t.copy(); t2['ntimes'] = t2['code'].map(cnt)
    rep = t2[t2['ntimes']>=3].dropna(subset=['exc5']); single = t2[t2['ntimes']<3].dropna(subset=['exc5'])
    print(f"{nm} 重复票n={len(rep)} exc5={rep['exc5'].mean():+.2f}%  单次票n={len(single)} exc5={single['exc5'].mean():+.2f}%")
    if len(rep): print("   重复票:", rep.groupby('code')['name'].first().head(10).to_dict())

print("\n=== 10. 两策略分歧票（CMMR Top10但CMMR+落榜 反之亦然）exc5 ===")
key_c = set(zip(top_c['d'], top_c['code'])); key_p = set(zip(top_cp['d'], top_cp['code']))
only_c = top_c[[(d,c) not in key_p for d,c in zip(top_c['d'],top_c['code'])]].dropna(subset=['exc5'])
only_p = top_cp[[(d,c) not in key_c for d,c in zip(top_cp['d'],top_cp['code'])]].dropna(subset=['exc5'])
inter  = top_c[[ (d,c) in key_p for d,c in zip(top_c['d'],top_c['code'])]].dropna(subset=['exc5'])
print(f"仅CMMR上榜: n={len(only_c)} exc5={only_c['exc5'].mean():+.2f}%")
print(f"仅CMMR+上榜: n={len(only_p)} exc5={only_p['exc5'].mean():+.2f}%")
print(f"双上榜: n={len(inter)} exc5={inter['exc5'].mean():+.2f}%")

print("\n=== 11. cmmrp高但cmmr低（模型分主导）vs cmmr高但cmmrp低（形态分主导）exc10 ===")
s3 = sig.copy(); s3 = attach_fwd(s3)
a = s3[(s3['cmmrp']>=80)&(s3['cmmr']<40)].dropna(subset=['exc10'])
b = s3[(s3['cmmr']>=80)&(s3['cmmrp']<40)].dropna(subset=['exc10'])
c = s3[(s3['cmmr']>=80)&(s3['cmmrp']>=80)].dropna(subset=['exc10'])
print(f"CMMR+≥80且CMMR<40 (n={len(a)}): exc10={a['exc10'].mean():+.2f}% 胜率{(a['exc10']>0).mean()*100:.0f}%")
print(f"CMMR≥80且CMMR+<40 (n={len(b)}): exc10={b['exc10'].mean():+.2f}% 胜率{(b['exc10']>0).mean()*100:.0f}%")
print(f"双≥80 (n={len(c)}): exc10={c['exc10'].mean():+.2f}% 胜率{(c['exc10']>0).mean()*100:.0f}%")

# 12. 策略账户8月净值
print("\n=== 12. 策略账户8月NAV ===")
nav = con.execute("""
SELECT account_id, REPLACE(date,'-','') d, nav, market_ret, n_pos
FROM led.strategy_accounts_legacy WHERE REPLACE(date,'-','') BETWEEN '20260801' AND '20260831'
ORDER BY account_id, d""").df()
if len(nav):
    for a_id, g in nav.groupby('account_id'):
        g = g.sort_values('d')
        r = (g['nav'].iloc[-1]/g['nav'].iloc[0]-1)*100
        print(f"  {a_id}: {g['nav'].iloc[0]:.0f} -> {g['nav'].iloc[-1]:.0f} ({r:+.1f}%) 均持仓{g['n_pos'].mean():.1f}")
else:
    print(con.execute("SELECT account_id,name FROM led.strategy_accounts_meta").df().to_string(index=False))