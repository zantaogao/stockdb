# 捕获率测试：榜票窗口期预测涨幅，不同介入时点能兑现百分之几
# 窗口=信号日后win个交易日; 窗口段=入场后到窗口末; 捕获率=策略收益/票自身窗口段收益(仅对窗口段为正的票=有肉可捕)
import sqlite3, duckdb
import pandas as pd, numpy as np
from scipy import stats
SIG='/Users/zantao/.hermes/stockdb/signals.db'; TUSH='/Users/zantao/.hermes/stockdb/tushare.db'
s=sqlite3.connect(SIG)

def run(board_sql, win, tag, cal_from):
    df=pd.read_sql(board_sql,s); df['date']=df['date'].str.replace('-','')
    df=df.sort_values(['date','score'],ascending=[True,False])
    top=df.groupby('date').head(10).copy(); top['rank']=top.groupby('date').cumcount()+1
    dates=sorted(top['date'].unique())
    d=duckdb.connect(TUSH,read_only=True)
    ic=d.execute(f"SELECT trade_date,close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='{cal_from}' ORDER BY trade_date").df().set_index('trade_date')['close']
    codes=sorted(top['stock_code'].unique())
    def suf(c): return c+'.SH' if c[0]=='6' else (c+'.BJ' if c[0] in '489' else c+'.SZ')
    cl=','.join("'"+suf(c)+"'" for c in codes)
    px=d.execute(f"SELECT p.ts_code,p.trade_date,p.open,p.high,p.low,p.close,a.adj_factor FROM daily p JOIN adj_factor a USING (ts_code,trade_date) WHERE p.ts_code IN ({cl}) AND p.trade_date>='20260601'").df(); d.close()
    px['f']=px.groupby('ts_code')['adj_factor'].transform(lambda x:x/x.iloc[-1])
    for c in ['open','high','low','close']: px['q'+c]=px[c]*px['f']
    px=px.sort_values(['ts_code','trade_date'])
    px['ma10']=px.groupby('ts_code')['qclose'].transform(lambda x:x.rolling(10).mean())
    book={t:g.set_index('trade_date') for t,g in px.groupby('ts_code')}

    strat_names=['T+1开盘','T+1收盘','等回踩MA10(收盘进)','等3连阳(收盘进)','等突破20日高(收盘进)']
    cap={k:[] for k in strat_names}; exc={k:[] for k in strat_names}  # 捕获率%; 超额捕获(策略收益-同期基准)
    missed={k:0 for k in strat_names}; total=0
    hi_dist=[]  # T+1进场时的"位置": close在窗口段最高价的比例
    for dd in dates:
        for _,row in top[top['date']==dd].iterrows():
            t=suf(row['stock_code']); g=book.get(t)
            if g is None: continue
            days=[x for x in g.index if x>dd]
            if len(days)-1<win: continue
            total+=1
            end=days[win]
            seg_end_close=g.loc[end,'qclose']
            seg_high=g.loc[days[1:win+1],'qhigh'].max()
            # T+1位置: 开盘价距窗口段最高的距离(追高程度)
            hi_dist.append(g.loc[days[0],'qopen']/seg_high-1)
            def rec(name, entry_px, entry_day):
                # 固定分母: 该票整个窗口段的兑现幅度(T+1开盘→窗末), 仅对窗末为正涨幅的票算捕获
                seg_full=(seg_end_close/g.loc[days[0],'qopen']-1)
                r=(seg_end_close/entry_px-1)*100
                b=(ic.loc[end]/ic.loc[entry_day]-1)*100
                exc[name].append((dd, r-b))
                if seg_full>0.01: cap[name].append((dd, r/(seg_full*100)*100))
            rec('T+1开盘', g.loc[days[0],'qopen'], days[0])
            rec('T+1收盘', g.loc[days[0],'qclose'], days[0])
            # 回踩MA10: 前7日内 low<=ma10 首次, 当日收盘进; 错过窗末则不记
            ent=None
            for k in range(1,8):
                x=days[k]
                if not np.isnan(g.loc[x,'ma10']) and g.loc[x,'qlow']<=g.loc[x,'ma10']: ent=k; break
            if ent: rec('等回踩MA10(收盘进)', g.loc[days[ent],'qclose'], days[ent])
            else: missed['等回踩MA10(收盘进)']+=1
            # 3连阳: 连续3根阳线(收盘>开盘)
            ent=None
            for k in range(2,8):
                a,b_,c_=days[k-2],days[k-1],days[k]
                if g.loc[a,'qclose']>g.loc[a,'qopen'] and g.loc[b_,'qclose']>g.loc[b_,'qopen'] and g.loc[c_,'qclose']>g.loc[c_,'qopen']:
                    ent=k; break
            if ent: rec('等3连阳(收盘进)', g.loc[days[ent],'qclose'], days[ent])
            else: missed['等3连阳(收盘进)']+=1
            # 突破20日高
            hi20=None
            ent=None
            for k in range(0,8):
                x=days[k]
                hist=[y for y in g.index if y<=x][-21:-1]
                if len(hist)<20: continue
                hh=g.loc[hist,'qhigh'].max()
                if g.loc[x,'qhigh']>hh: ent=k; break
            if ent: rec('等突破20日高(收盘进)', g.loc[days[ent],'qclose'], days[ent])
            else: missed['等突破20日高(收盘进)']+=1
    hd=np.array(hi_dist)*100
    print(f'\n== {tag} | {total}笔(窗口{win}日) | T+1开盘价距窗口段最高: 中位{np.median(hd):+.1f}%(=进场即距顶的距离)')
    print('%-22s 捕获率中位%% 捕获率均值%%  超额捕获pp   漏单' % '介入策略')
    daily_ex={}
    for name in strat_names:
        c=np.array([v for _,v in cap[name]]); e=pd.Series([v for k,v in exc[name]]).groupby([k for k,_ in exc[name]]).mean()
        daily_ex[name]=e
        mm=missed[name] if missed[name] else '-'
        print('%-22s %8.0f %10.0f %10.2f   %s' % (name, np.median(c), c.mean(), e.mean(), mm))
    base=daily_ex['T+1开盘']
    for name in strat_names[1:]:
        j=pd.concat([base.rename('a'),daily_ex[name].rename('b')],axis=1).dropna()
        t,p=stats.ttest_ind(j['b'],j['a'],equal_var=False)
        print('  vs T+1开盘: %s 超额捕获 %+.2fpp (t=%.2f p=%.3f)' % (name, j['b'].mean()-j['a'].mean(), t, p))

run("SELECT date, stock_code, fusion_score AS score FROM signal_history", 10, '三模型融合榜top10', '20260701')
run("SELECT date, stock_code, score FROM fusion_center_signals", 20, '中枢版榜top10', '20260806')
