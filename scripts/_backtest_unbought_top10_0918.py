# 未买top10（按资金只买得起前3）：4-10名隔几天再进 vs 已买前3 —— 换仓/补票有没有肉
import sqlite3, duckdb, json
import pandas as pd, numpy as np
SIG='/Users/zantao/.hermes/stockdb/signals.db'; TUSH='/Users/zantao/.hermes/stockdb/tushare.db'
s=sqlite3.connect(SIG)

def run(board_sql, win, tag, cal_from):
    df=pd.read_sql(board_sql,s); df['date']=df['date'].str.replace('-','')
    df=df.sort_values(['date','score'],ascending=[True,False])
    top=df.groupby('date').head(10).copy()
    top['rank']=top.groupby('date').cumcount()+1
    dates=sorted(top['date'].unique())
    d=duckdb.connect(TUSH,read_only=True)
    ic=d.execute(f"SELECT trade_date,close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='{cal_from}' ORDER BY trade_date").df().set_index('trade_date')['close']
    codes=sorted(top['stock_code'].unique())
    def suf(c): return c+'.SH' if c[0]=='6' else (c+'.BJ' if c[0] in '489' else c+'.SZ')
    cl=','.join("'"+suf(c)+"'" for c in codes)
    px=d.execute(f"SELECT p.ts_code,p.trade_date,p.open,p.high,p.low,p.close,a.adj_factor FROM daily p JOIN adj_factor a USING (ts_code,trade_date) WHERE p.ts_code IN ({cl}) AND p.trade_date>='20260601'").df()
    d.close()
    px['f']=px.groupby('ts_code')['adj_factor'].transform(lambda x:x/x.iloc[-1])
    for c in ['open','high','low','close']: px['q'+c]=px[c]*px['f']
    px=px.sort_values(['ts_code','trade_date'])
    px['ma10']=px.groupby('ts_code')['qclose'].transform(lambda x:x.rolling(10).mean())
    px['ma5']=px.groupby('ts_code')['qclose'].transform(lambda x:x.rolling(5).mean())
    book={t:g.set_index('trade_date') for t,g in px.groupby('ts_code')}
    def ret_entry(t,dd0,k,hold):  # 信号日dd0后第k个交易日收盘进, 持hold日(封顶数据尾)
        g=book[t]; days=[x for x in g.index if x>dd0]
        if len(days)-1<k+1: return None,None
        e=days[k]; end=min(k+hold,len(days)-1)
        if end<=k: return None,None
        r=g.loc[days[end],'qclose']/g.loc[e,'qclose']-1
        b=ic.loc[days[end]]/ic.loc[e]-1
        return r*100,(r-b)*100
    strat={'前3已买(T+1开盘,持满窗)':[], '4-10 T+1就补':[], '4-10 等回踩MA10':[], '4-10 第3天硬补':[], '4-10 第5天硬补':[]}
    trig_days=[]
    for dd in dates:
        sub=top[top['date']==dd]
        bought_r=[]
        for _,row in sub[sub['rank']<=3].iterrows():
            t=suf(row['stock_code'])
            if t not in book: continue
            g=book[t]; days=[x for x in g.index if x>dd]
            if len(days)-1<win: continue
            end=min(win,len(days)-1)
            r=g.loc[days[end],'qclose']/g.loc[days[0],'qopen']-1
            b=ic.loc[days[end]]/ic.loc[days[0]]-1
            bought_r.append((r*100,(r-b)*100))
        if bought_r:
            strat['前3已买(T+1开盘,持满窗)'].extend(bought_r)
        for _,row in sub[(sub['rank']>=4)].iterrows():
            t=suf(row['stock_code'])
            if t not in book: continue
            g=book[t]; days=[x for x in g.index if x>dd]
            if len(days)-1<win: continue
            # T+1收盘补
            end=min(win,len(days)-1)
            r=g.loc[days[end],'qclose']/g.loc[days[1],'qclose']-1; b=ic.loc[days[end]]/ic.loc[days[1]]-1
            strat['4-10 T+1就补'].append((r*100,(r-b)*100))
            # 等回踩MA10(前10日内首次 low<=ma10), 触发日收盘进, 持到窗满/进后win
            entered=None
            for k in range(1,min(10,len(days)-1)):
                x=days[k]
                if not np.isnan(g.loc[x,'ma10']) and g.loc[x,'qlow']<=g.loc[x,'ma10']:
                    entered=k; break
            if entered is not None:
                end=min(entered+win,len(days)-1)
                if end>entered:
                    r=g.loc[days[end],'qclose']/g.loc[days[entered],'qclose']-1
                    b=ic.loc[days[end]]/ic.loc[days[entered]]-1
                    strat['4-10 等回踩MA10'].append((r*100,(r-b)*100)); trig_days.append(entered)
            # 第k天硬补
            for k,lbl in [(3,'4-10 第3天硬补'),(5,'4-10 第5天硬补')]:
                end=min(k+win,len(days)-1)
                if end>k:
                    r=g.loc[days[end],'qclose']/g.loc[days[k],'qclose']-1
                    b=ic.loc[days[end]]/ic.loc[days[k]]-1
                    strat[lbl].append((r*100,(r-b)*100))
    print(f'\n== {tag} (窗口{win}交易日, 信号日{len(dates)})')
    for lbl,rows in strat.items():
        if not rows: print(lbl,'无'); continue
        a=np.array([x[0] for x in rows]); e=np.array([x[1] for x in rows])
        print('  %-22s n=%3d | 收益均 %+6.2f%% | 超额均 %+6.2fpp | 胜率 %2.0f%%' % (lbl,len(a),a.mean(),e.mean(),(a>0).mean()*100))
    if trig_days: print('  回踩触发耗时中位: 第%d日' % int(np.median(trig_days)))

run("SELECT date, stock_code, fusion_score AS score FROM signal_history", 10, '三模型融合榜: 前3已买 vs 4-10名补票时点', '20260701')
run("SELECT date, stock_code, score FROM fusion_center_signals", 20, '中枢版榜: 前3已买 vs 4-10名补票时点', '20260806')
