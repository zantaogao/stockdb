# 中枢版榜·满窗口跟踪回测：名单给分后20个交易日内，"连跌后企稳再介入" vs "立即买入持满窗"
# 中枢榜 top10/信号日, 跟踪窗口20交易日(用户口径), 截止数据20260918, 只统计已走满或接近走满的
import sqlite3, duckdb, json
import pandas as pd, numpy as np

SIG='/Users/zantao/.hermes/stockdb/signals.db'; TUSH='/Users/zantao/.hermes/stockdb/tushare.db'
s=sqlite3.connect(SIG)
fc=pd.read_sql("SELECT date, stock_code, stock_name, score FROM fusion_center_signals", s)
fc['date']=fc['date'].str.replace('-','')
fc=fc.sort_values(['date','score'],ascending=[True,False])
top10=fc.groupby('date').head(10)
sig_dates=sorted(top10['date'].unique())

d=duckdb.connect(TUSH,read_only=True)
cal=[r[0] for r in d.execute("SELECT DISTINCT trade_date FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='20260801' ORDER BY trade_date").fetchall()]
codes=sorted(top10['stock_code'].unique())
def suf(c): return c+'.SH' if c[0]=='6' else (c+'.BJ' if c[0] in '489' else c+'.SZ')
cl=','.join("'"+suf(c)+"'" for c in codes)
px=d.execute(f"SELECT p.ts_code,p.trade_date,p.open,p.high,p.low,p.close,a.adj_factor FROM daily p JOIN adj_factor a USING (ts_code,trade_date) WHERE p.ts_code IN ({cl}) AND p.trade_date BETWEEN '20260701' AND '20260918'").df()
idx=d.execute("SELECT trade_date,close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='20260801' ORDER BY trade_date").df()
d.close()
px['f']=px.groupby('ts_code')['adj_factor'].transform(lambda x:x/x.iloc[-1])
for c in ['open','high','low','close']: px['q_'+c]=px[c]*px['f']
px=px.sort_values(['ts_code','trade_date'])
px['ma20']=px.groupby('ts_code')['q_close'].transform(lambda x:x.rolling(20).mean())
px['ma5']=px.groupby('ts_code')['q_close'].transform(lambda x:x.rolling(5).mean())
book={t:g.set_index('trade_date') for t,g in px.groupby('ts_code')}
ic=idx.set_index('trade_date')['close']
def iret(a,b):
    try: return ic.loc[b]/ic.loc[a]-1
    except: return None

WIN=20
res={'A_immediate':[], 'B_stabilize':[], 'B_notrig':[]}
for sd in sig_dates:
    if sd < '20260806': continue  # 中枢榜首日
    for _,row in top10[top10['date']==sd].iterrows():
        t=suf(row['stock_code'])
        if t not in book: continue
        g=book[t]
        days=[dd for dd in g.index if dd>sd]
        if len(days)<3: continue
        end_a=min(WIN,len(days)-1)
        full=len(days)-1>=WIN
        # A 立即 T+1开盘 持到 min(20d, 数据尾)
        pa=g.loc[days[end_a],'q_close']/g.loc[days[0],'q_open']-1
        ba=iret(days[0],days[end_a])
        if full: res['A_immediate'].append((sd,row['stock_code'],row['stock_name'],float(pa*100),float(ba*100) if ba is not None else None))
        # B 企稳信号介入: 观察期前10日内, 找"此前累计跌(相对T+1开盘)<=-2%, 且当日收阳并收复前日高点, 且收盘>ma5" 第一天
        entry=None
        base=g.loc[days[0],'q_open']
        for k in range(1,min(10,len(days)-1)):
            dd=days[k]; pv=days[k-1]
            cum=g.loc[dd,'q_low']/base-1
            if cum<=-0.02 and g.loc[dd,'q_close']>g.loc[pv,'q_close'] and g.loc[dd,'q_close']>g.loc[pv,'q_high'] and g.loc[dd,'q_close']>g.loc[dd,'ma5'] and not np.isnan(g.loc[dd,'ma5']):
                entry=k; break
        if entry is not None:
            end=min(entry+WIN,len(days)-1)
            if end>entry:
                pb=g.loc[days[end],'q_close']/g.loc[days[entry],'q_close']-1
                bb=iret(days[entry],days[end])
                res['B_stabilize'].append((sd,row['stock_code'],row['stock_name'],float(pb*100),float(bb*100) if bb is not None else None,entry,len(days)-1-entry))
        else:
            res['B_notrig'].append((sd,row['stock_code'],float(pa*100) if full else None))

def summ(rows,label):
    if not rows: print(label,'无'); return
    r=np.array([x[3] for x in rows]); b=np.array([x[4] for x in rows if x[4] is not None]); e=(r.mean()-b.mean()) if len(b) else np.nan
    print(f"{label}: n={len(rows)} 均{r.mean():+.2f}% 中位{np.median(r):+.2f}% 胜率{(r>0).mean()*100:.0f}% | 基准{b.mean() if len(b) else float('nan'):+.2f}% 超额{e:+.2f}pp")

print('中枢榜信号日数:', len([x for x in sig_dates if x>='20260806']))
summ(res['A_immediate'],'A 立即买持满20日窗(走满的)')
summ(res['B_stabilize'],'B 企稳信号介入(跌≥2%后收阳收复前高上MA5, 持≤20日)')
nt=[x for x in res['B_notrig'] if x[2] is not None]
if nt:
    r=np.array([x[2] for x in nt]); print(f"B未触发(踏空组): n={len(nt)} 若立即买均值{r.mean():+.2f}% 胜率{(r>0).mean()*100:.0f}%")
if res['B_stabilize']:
    tg=np.array([x[5] for x in res['B_stabilize']]); print('企稳触发耗时: 中位%d日 均值%.1f 分布%s'%(np.median(tg),tg.mean(),dict(zip(*np.unique(tg,return_counts=True)))))
json.dump(res,open('/Users/zantao/.hermes/stockdb/scripts/_track_center_rows_0918.json','w'),ensure_ascii=False,default=str)
print('存 _track_center_rows_0918.json')
