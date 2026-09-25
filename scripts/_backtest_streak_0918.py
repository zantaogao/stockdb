# 反事实：资金有限挑着买 vs 跟踪未买票等后续信号
# 分层：信号日票在最近5个信号日的"在榜天数"1-5 → 后续10日/20日收益+超额
import sqlite3, duckdb
import pandas as pd, numpy as np
SIG='/Users/zantao/.hermes/stockdb/signals.db'; TUSH='/Users/zantao/.hermes/stockdb/tushare.db'
s=sqlite3.connect(SIG)

def run(board_sql, topn, win, tag, cal_from):
    df=pd.read_sql(board_sql,s)
    df['date']=df['date'].str.replace('-','')
    df=df.sort_values(['date','score'],ascending=[True,False])
    top=df.groupby('date').head(topn).copy()
    dates=sorted(top['date'].unique())
    dset={d:set(top[top['date']==d]['stock_code']) for d in dates}
    # 在榜天数(含当日, 最近5信号日)
    days5=[]
    for i,dd in enumerate(dates):
        cnt={}
        for j in range(max(0,i-4),i+1):
            for c in dset[dates[j]]: cnt[c]=cnt.get(c,0)+1
        days5.append(cnt)
    cnt_by_day=dict(zip(dates,days5))
    d=duckdb.connect(TUSH,read_only=True)
    cal=[r[0] for r in d.execute(f"SELECT DISTINCT trade_date FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='{cal_from}' ORDER BY trade_date").fetchall()]
    ic=d.execute(f"SELECT trade_date,close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='{cal_from}' ORDER BY trade_date").df().set_index('trade_date')['close']
    codes=sorted(top['stock_code'].unique())
    def suf(c): return c+'.SH' if c[0]=='6' else (c+'.BJ' if c[0] in '489' else c+'.SZ')
    cl=','.join("'"+suf(c)+"'" for c in codes)
    px=d.execute(f"SELECT p.ts_code,p.trade_date,p.close,a.adj_factor FROM daily p JOIN adj_factor a USING (ts_code,trade_date) WHERE p.ts_code IN ({cl}) AND p.trade_date>='20260601'").df()
    d.close()
    px['f']=px.groupby('ts_code')['adj_factor'].transform(lambda x:x/x.iloc[-1])
    px['q']=px['close']*px['f']
    book={t:g.set_index('trade_date')['q'] for t,g in px.groupby('ts_code')}
    print(f'\n== {tag}: top{topn}×{len(dates)}信号日, 窗口{win}交易日')
    print('在榜天数 | n | 持%d日均益%% | 超额pp | 胜率%%' % win)
    for lvl in range(1,6):
        rets=[]; exs=[]
        for dd in dates:
            base=cnt_by_day[dd]
            for c in dset[dd]:
                if base.get(c,0)!=lvl: continue
                t=suf(c)
                if t not in book: continue
                q=book[t]; days=[x for x in q.index if x>dd]
                if len(days)-1<win: continue
                r=q.loc[days[win]]/q.loc[days[0]]-1
                b=ic.loc[days[win]]/ic.loc[days[0]]-1
                rets.append(r*100); exs.append((r-b)*100)
        if len(rets)>=8:
            r=np.array(rets); e=np.array(exs)
            print('  %d日在榜 | %3d | %+6.2f | %+6.2f | %2.0f%%' % (lvl,len(r),r.mean(),e.mean(),(r>0).mean()*100))

run("SELECT date, stock_code, fusion_score AS score FROM signal_history", 50, 10, '三模型融合榜 top50', '20260701')
run("SELECT date, stock_code, score FROM fusion_center_signals", 50, 20, '中枢版榜 top50', '20260806')
