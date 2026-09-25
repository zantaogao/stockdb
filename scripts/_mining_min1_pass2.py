#!/usr/bin/env python3
"""分钟线特征研究 第二轮（2026-09-02）
研究窗: 20260224-20260722（历史基线，~100交易日全市场）
验证窗: 20260826-20260902（有模型信号，测增量IC）
输出: 按日截面 Rank IC 月度分解 + t值；验证窗做控制 reg10_pred/day_ret 的残差IC。
"""
import pandas as pd, numpy as np, duckdb, sqlite3, sys

BASE_DIR = '/Users/zantao/.hermes/stockdb'
feat = pd.read_parquet(f'{BASE_DIR}/analysis/min1_features_0902.parquet')

daily = duckdb.connect(f'{BASE_DIR}/tushare.db', read_only=True).execute(
    "SELECT REPLACE(trade_date,'-','') AS date, ts_code AS code, close FROM daily WHERE trade_date >= '20260212'").df()
daily['code'] = daily['code'].str[:6]
d = daily.sort_values(['code','date']).copy()
for h in (1,3,5,10):
    d[f'fwd{h}'] = d.groupby('code')['close'].shift(-h)/d['close'] - 1

base = feat.merge(d[['date','code','fwd1','fwd3','fwd5','fwd10']], on=['date','code'], how='inner')
print('research sample:', len(base))

feats = ['open30_ret','tail30_ret','tail5_ret','tail_up_ratio','vwap_dev','rv_1m','amp_intra',
         'gap_ret','vd_o30','vd_m1','vd_m2','vd_t30','last_vol_share','tail_vwap_dev','day_ret']

def ic_series(df, f, t):
    out = {}
    for dt, g in df.groupby('date'):
        g = g[[f,t]].dropna()
        if len(g) < 100: continue
        out[dt] = np.corrcoef(g[f].rank(), g[t].rank())[0,1]
    return pd.Series(out)

research = base[(base['date']>='20260224') & (base['date']<='20260722')]
print('research window rows:', len(research), 'days:', research['date'].nunique())

rows = []
for f in feats:
    for t in ['fwd1','fwd3','fwd5','fwd10']:
        ics = ic_series(research, f, t)
        if len(ics) < 20: continue
        m, s = ics.mean(), ics.std()
        row = {'feat':f,'target':t,'ic':round(m,4),'t':round(m/(s/np.sqrt(len(ics))),1),
               'days':len(ics),'win':round((ics>0).mean(),2)}
        # 月度分解
        ics_m = ics.copy(); ics_m.index = ics_m.index.str[:6]
        for mo, g in ics_m.groupby(level=0):
            row[f'm{mo[4:]}'] = round(g.mean(),3)
        rows.append(row)
res = pd.DataFrame(rows)
pd.set_option('display.width',250)
for t in ['fwd1','fwd5','fwd10']:
    sub = res[res['target']==t].sort_values('ic')
    print(f'\n=== 研究窗 2/24-7/22 截面IC ({t}) ===')
    print(sub.to_string(index=False))
res.to_csv(f'{BASE_DIR}/analysis/min1_ic_research_0902.csv', index=False)

# 组合检验: 研究窗内 Top特征合成信号的五分组单调性
print('\n=== 五分组年化超额（研究窗, fwd5）===')
strong = res[(res['target']=='fwd5')].copy()
strong['absic'] = strong['ic'].abs()
top5 = strong.nsmallest(5,'ic')['feat'].tolist() + strong.nlargest(5,'ic')['feat'].tolist()
print('入选特征:', top5)
b2 = research.dropna(subset=top5+['fwd5']).copy()
ic_sign = strong.set_index('feat')['ic'].to_dict()
b2['sig'] = sum(b2[f].rank(pct=True) * np.sign(ic_sign[f]) for f in top5)
b2['q'] = b2.groupby('date')['sig'].transform(lambda x: pd.qcut(x.rank(method='first'), 5, labels=False))
qret = b2.groupby(['date','q'])['fwd5'].mean().unstack()
qmean = qret.mean()
print('Q1..Q5 日均收益%:', (qmean*100).round(3).to_list())
print('Q5-Q1 日均:', round((qmean.iloc[-1]-qmean.iloc[0])*100,3), '% | 日胜率:', round(((qret[4]-qret[0])>0).mean(),2))