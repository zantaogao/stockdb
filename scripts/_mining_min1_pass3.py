#!/usr/bin/env python3
"""分钟线特征 第三轮: 中性化IC + 条件IC + 尾笔artifact核查
1) 最后1笔量核查（是否集合竞价巨量artifact）
2) 行业+市值中性化后的截面IC
3) 条件IC: 在"当日已上涨"子集内的尾拉/高波动区分度（对应实盘场景）
4) 验证窗 8/26-9/02: 对现有信号 reg10_pred/fusion_3f 的增量IC
"""
import pandas as pd, numpy as np, duckdb, sqlite3

BASE='/Users/zantao/.hermes/stockdb'
feat = pd.read_parquet(f'{BASE}/analysis/min1_features_0902.parquet')

# 1) 最后1笔量核查
arch = duckdb.connect(f'{BASE}/tdx_archive.db', read_only=True)
chk = arch.execute("""
WITH m AS (SELECT CAST(date AS VARCHAR) date, code, tm, volume,
   ROW_NUMBER() OVER (PARTITION BY date,code ORDER BY tm DESC) rn
   FROM min1_archive WHERE date=20260720 AND (code LIKE '0%' OR code LIKE '3%' OR code LIKE '6%'))
SELECT code, MAX(CASE WHEN rn=1 THEN tm END) last_tm, MAX(CASE WHEN rn=1 THEN volume END) last_vol,
       SUM(volume) tot_vol, AVG(CASE WHEN rn BETWEEN 2 AND 20 THEN volume END) avg_prev19
FROM m WHERE rn<=20 GROUP BY code LIMIT 8
""").df()
chk['last_over_avg'] = chk['last_vol']/chk['avg_prev19']
print('=== 最后1笔 vs 前19笔均量 (0720样本) ===')
print(chk[['code','last_tm','last_vol','avg_prev19','last_over_avg']].round(1).to_string(index=False))
tail_share = arch.execute("""
WITH m AS (SELECT CAST(date AS VARCHAR) date, code, tm, volume,
   ROW_NUMBER() OVER (PARTITION BY date,code ORDER BY tm DESC) rn
   FROM min1_archive WHERE date BETWEEN '20260302' AND '20260720' AND (code LIKE '0%' OR code LIKE '3%' OR code LIKE '6%'))
SELECT AVG(v1)/AVG(tot) ratio FROM (SELECT date,code,SUM(volume) tot, MAX(CASE WHEN rn=1 THEN volume END) v1 FROM m WHERE rn<=240 GROUP BY 1,2)
""").fetchone()
print('全窗 最后1笔/全日量 均值比:', round(tail_share[0],4))
arch.close()

# 2) 行业+规模(成交额)中性化
daily = duckdb.connect(f'{BASE}/tushare.db', read_only=True).execute("""
SELECT REPLACE(d.trade_date,'-','') AS date, d.ts_code AS code, d.close, d.amount,
       COALESCE(b.industry,'') AS industry
FROM daily d LEFT JOIN stock_basic b ON b.ts_code = d.ts_code
WHERE d.trade_date >= '20260212'""").df()
daily['code']=daily['code'].str[:6]
d = daily.sort_values(['code','date']).copy()
for h in (1,5,10):
    d[f'fwd{h}'] = d.groupby('code')['close'].shift(-h)/d['close']-1
d['logamt'] = np.log1p(d['amount'])

base = feat.merge(d[['date','code','fwd1','fwd5','fwd10','logamt','industry']], on=['date','code'], how='inner')
research = base[(base['date']>='20260302')&(base['date']<='20260720')]
print('\nresearch rows:', len(research), 'days:', research['date'].nunique())

feats = ['tail5_ret','tail30_ret','last_vol_share','rv_1m','amp_intra','vd_o30','gap_ret','vd_m1','day_ret']

def neutral_ic(df, f, t, ctrl):
    ics=[]
    for dt,g in df.groupby('date'):
        g=g.dropna(subset=[f,t]+ctrl)
        if len(g)<100: continue
        y=g[t].rank(pct=True).values; x=g[f].rank(pct=True).values
        # 控制变量: 行业dummies + ctrl连续变量 rank
        ind=pd.get_dummies(g['industry'],drop_first=True).values.astype(float)
        C=[np.ones((len(g),1))]+[g[c].rank(pct=True).values.reshape(-1,1) for c in ctrl if c!='industry']+[ind]
        X=np.hstack(C)
        by,_,_,_=np.linalg.lstsq(X,y,rcond=None); bx,_,_,_=np.linalg.lstsq(X,x,rcond=None)
        ry=y-X@by; rx=x-X@bx
        s=rx.std()
        if s>0: ics.append(np.corrcoef(rx,ry)[0,1])
    ics=pd.Series(ics)
    return ics.mean(), ics.mean()/(ics.std()/np.sqrt(len(ics))), len(ics)

print('\n=== 行业+成交额中性化后 截面IC (研究窗3/2-7/20) ===')
rows=[]
for f in feats:
    for t in ['fwd1','fwd5','fwd10']:
        m,tst,n = neutral_ic(research,f,t,['industry','logamt'])
        rows.append({'feat':f,'target':t,'ic':round(m,4),'t':round(tst,1),'days':n})
print(pd.DataFrame(rows).sort_values('target').to_string(index=False))

# 3) 条件IC: 当日上涨股子集
print('\n=== 条件IC: 当日涨幅>2%子集内 (fwd1) ===')
up = research[research['day_ret']>0.02]
for f in ['tail5_ret','last_vol_share','rv_1m','tail30_ret','vwap_dev' if 'vwap_dev' in up.columns else 'gap_ret']:
    if f not in up.columns: continue
    m,tst,n = neutral_ic(up,f,'fwd1',['industry','logamt'])
    print(f'{f}: ic={m:.4f} t={tst:.1f} days={n}')

# 4) 验证窗增量IC: 控制 reg10_pred / fusion_3f_score 后特征残差IC (fwd1/fwd5)
sc = sqlite3.connect(f'{BASE}/signals.db')
sig = pd.read_sql("SELECT date, stock_code AS code, reg10_pred FROM signal_history", sc)
sig['date']=sig['date'].str.replace('-','',regex=False)
sig=sig.drop_duplicates(['date','code'],keep='last')
f3 = pd.read_sql("SELECT date, stock_code AS code, fusion_3f_score FROM fusion_3f_signals", sc)
f3['date']=f3['date'].str.replace('-','',regex=False)
sc.close()
recent = base[(base['date']>='20260826')&(base['date']<='20260827')]  # fwd5可算的窗口
recent = recent.merge(sig,on=['date','code'],how='inner').merge(f3,on=['date','code'],how='left')
print('\n验证窗 rows:', len(recent))
def resid_ic(df, f, t, ctrl):
    ics=[]
    for dt,g in df.groupby('date'):
        g=g.dropna(subset=[f,t]+ctrl)
        if len(g)<100: continue
        y=g[t].rank(pct=True).values; x=g[f].rank(pct=True).values
        X=np.hstack([np.ones((len(g),1))]+[g[c].rank(pct=True).values.reshape(-1,1) for c in ctrl])
        by,*_=np.linalg.lstsq(X,y,rcond=None); bx,*_=np.linalg.lstsq(X,x,rcond=None)
        ry=y-X@by; rx=x-X@bx
        if rx.std()>0: ics.append(np.corrcoef(rx,ry)[0,1])
    ics=pd.Series(ics); return ics.mean(), len(ics)
for ctrl_name,ctrl in [('reg10_pred',['reg10_pred']),('fusion_3f',['fusion_3f_score'])]:
    print(f'--- 控制 {ctrl_name} (fwd1) ---')
    for f in ['tail5_ret','last_vol_share','gap_ret','rv_1m','tail30_ret']:
        m,n = resid_ic(recent,f,'fwd1',ctrl)
        print(f'  {f}: resid_ic={m:.4f} days={n}')