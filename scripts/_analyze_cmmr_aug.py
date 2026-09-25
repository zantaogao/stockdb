#!/usr/bin/env python3
"""8月 CMMR / CMMR+ 信号统计与规律挖掘（只读分析）"""
import duckdb, pandas as pd, numpy as np

con = duckdb.connect('tushare.db', read_only=True)
con.execute("ATTACH 'signals.db' AS sig (TYPE sqlite, READ_ONLY)")
con.execute("ATTACH 'ledger.db' AS led (TYPE sqlite, READ_ONLY)")

pd.set_option('display.width', 200)
pd.set_option('display.max_columns', 50)

# ---- 1. 信号面板：8月每日 cmmr_score / fusion_score_cmmr 分布
sig = con.execute("""
SELECT REPLACE(date,'-','') AS d, stock_code, stock_name, industry,
       cmmr_score AS cmmr, fusion_score_cmmr AS cmmrp, final_score
FROM sig.signal_history
WHERE REPLACE(date,'-','') BETWEEN '20260801' AND '20260831'
""").df()
sig['stock_code'] = sig['stock_code'].str.replace(r'\.\w+$','',regex=True)

daily = sig.groupby('d').agg(
    n=('cmmr','size'),
    cmmr_mean=('cmmr','mean'), cmmr_max=('cmmr','max'),
    cmmrp_mean=('cmmrp','mean'), cmmrp_max=('cmmrp','max'),
    cmmr_ge80=('cmmr', lambda s:(s>=80).sum()),
    cmmrp_ge80=('cmmrp', lambda s:(s>=80).sum()),
).round(2)
print("=== 每日信号分布 ===")
print(daily.to_string())

# ---- 2. 两个策略Top10的重合度 & 各自Top10的分数区间
top_c  = sig.sort_values('cmmr', ascending=False).groupby('d').head(10)
top_cp = sig.sort_values('cmmrp', ascending=False).groupby('d').head(10)
ov = top_c.merge(top_cp, on=['d','stock_code'], how='inner')
print("\n=== Top10 重合度（CMMR vs CMMR+）===")
ovd = ov.groupby('d').size()
print(ovd.to_string())
print("平均重合:", round(ovd.mean(),2), "/10")

# 相关系数（同日全样本 spearman）
corr = sig.groupby('d').apply(lambda g: g['cmmr'].corr(g['cmmrp'], method='spearman'))
print("cmmr vs cmmrp 日度spearman 均值:", round(corr.mean(),3))

# ---- 3. Top10 前向收益（5/10/20交易日）
dates = sorted(sig['d'].unique())
# 用 daily 行情算前向收益
cal = con.execute("""
SELECT DISTINCT trade_date FROM daily WHERE trade_date BETWEEN '20260601' AND '20260930'
ORDER BY trade_date""").df()['trade_date'].tolist()
didx = {d:i for i,d in enumerate(cal)}

def fwd_returns(picks, horizons=(3,5,10)):
    rows=[]
    codes = picks['stock_code'].unique().tolist()
    dl = con.execute(f"""
      SELECT REPLACE(ts_code,'.SZ','') .REPLACE. FROM daily LIMIT 0""").df() if False else None
    dl = con.execute(f"""
      SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') AS code, trade_date AS d, close, pct_chg
      FROM daily WHERE trade_date BETWEEN '20260601' AND '20260930'
        AND REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') IN ({','.join(chr(39)+c+chr(39) for c in codes)})
    """).df()
    closes = dl.pivot(index='code', columns='d', values='close')
    mkt = con.execute("""
      SELECT trade_date d, AVG(pct_chg) mkt_ret FROM daily
      WHERE trade_date BETWEEN '20260601' AND '20260930' GROUP BY d""").df().set_index('d')['mkt_ret']
    for _,r in picks.iterrows():
        d=r['d']; code=r['stock_code']
        if code not in closes.index or d not in didx: continue
        i=didx[d]
        rec={'d':d,'code':code,'name':r['stock_name'],'industry':r['industry'],'score':None}
        for h in horizons:
            if i+h < len(cal):
                nd=cal[i+h]
                try:
                    c0=closes.loc[code,d]; c1=closes.loc[code,nd]
                    if pd.notna(c0) and pd.notna(c1) and c0>0:
                        rec[f'fwd{h}']=(c1/c0-1)*100
                        rec[f'exc{h}']=(c1/c0-1)*100 - mkt.loc[cal[i+1:i+h+1]].sum()
                except KeyError: pass
        rows.append(rec)
    return pd.DataFrame(rows)

for name, picks, scol in [('CMMR', top_c, 'cmmr'), ('CMMR+', top_cp, 'cmmrp')]:
    p = picks[['d','stock_code','stock_name','industry',scol]].rename(columns={scol:'score', 'stock_code':'code'})
    fr = fwd_returns(p)
    merged = p.merge(fr, on=['d','code'], how='left', suffixes=('','_r'))
    globals()['fr_'+name] = merged
    print(f"\n=== {name} Top10 前向收益汇总（8月）===")
    for h in (3,5,10):
        s=merged[f'fwd{h}'].dropna(); e=merged[f'exc{h}'].dropna()
        if len(s): print(f"  fwd{h:>2}: 均收益 {s.mean():+.2f}%  超额 {e.mean():+.2f}%  胜率 {(s>0).mean()*100:.0f}%  超额胜率 {(e>0).mean()*100:.0f}%  n={len(s)}")
    # 分数与收益关系
    for h in (5,10):
        sub=merged.dropna(subset=['score',f'fwd{h}'])
        if len(sub)>20:
            print(f"  score vs fwd{h} IC(spearman): {sub['score'].corr(sub[f'fwd{h}'],method='spearman'):+.3f}")
    # 行业分布
    print("  行业分布(次数):", merged['industry'].value_counts().head(8).to_dict())

# ---- 4. 高分段 vs 低分段（验证分数单调性）
print("\n=== 分数分段 vs 前向10日收益（全样本抽样）===")
samp = sig.sample(min(3000,len(sig)), random_state=42)
fs = fwd_returns(samp.rename(columns={'cmmrp':'score'})[['d','stock_code','stock_name','industry','score']])
m = samp.merge(fs, on=['d','code'], how='left')
m['bucket'] = pd.cut(m['score'], [0,20,40,60,80,100])
print(m.groupby('bucket').agg(n=('fwd10','size'), 均fwd10=('fwd10','mean'), 超额=('exc10','mean'), 胜率=('fwd10',lambda s:(s>0).mean()*100)).round(2).to_string())

# ---- 5. 策略账户实际交易（CMMR/CMMR+账户）
print("\n=== 策略账户8月实际成交（trade_log）===")
tl = con.execute("""
SELECT strategy, direction, COUNT(*) n, SUM(amount) amt,
       MIN(trade_date) first, MAX(trade_date) last
FROM led.trade_log WHERE trade_date BETWEEN '2026-08-01' AND '2026-08-31'
GROUP BY strategy, direction ORDER BY strategy, direction""").df()
print(tl.to_string(index=False))

# NAV
nav = con.execute("""
SELECT account_id, REPLACE(date,'-','') d, nav, daily_ret, market_ret, n_pos
FROM led.strategy_accounts_legacy
WHERE REPLACE(date,'-','') BETWEEN '20260801' AND '20260831'
  AND account_id IN ('cmmr','cmmr_fusion','cmmr_plus')
ORDER BY account_id, d""").df()
if len(nav):
    print("\n=== 策略账户NAV（8月）===")
    for a,g in nav.groupby('account_id'):
        g=g.sort_values('d')
        ret=(g['nav'].iloc[-1]/g['nav'].iloc[0]-1)*100
        print(f"  {a}: 起点{g['nav'].iloc[0]:.0f} → 终点{g['nav'].iloc[-1]:.0f} ({ret:+.1f}%), 市场同日 {g['market_ret'].sum():+.1f}%, 持仓数均值 {g['n_pos'].mean():.1f}")
else:
    print("legacy NAV 无8月 cmmr 账户数据")
    accs = con.execute("SELECT account_id,name FROM led.strategy_accounts_meta").df()
    print(accs.to_string(index=False))