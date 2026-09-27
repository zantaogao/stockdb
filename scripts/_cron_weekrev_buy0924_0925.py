import pandas as pd
# buy-day intraday: what happened after each 09-24 buy (entry timing quality)
for code, name, px in [('603382','海阳科技',19.01),('300500','启迪设计',9.61),('688659','元琛科技',9.32),('300982','苏文电能',14.39),('301276','嘉曼服饰',17.56),('003027','同兴科技',16.66)]:
    pref='sh_' if code.startswith('6') else 'sz_'
    df=pd.read_parquet(f'minutes/5min/{pref}{code}.parquet')
    d=df[df['date']=='2026-09-24']
    close=float(d['close'].iloc[-1]); hi=float(d['high'].max())
    print(f'{name} buy@{px} -> day_close={close} after-buy={(close/px-1)*100:+.2f}% day_hi={hi} hi_vs_buy={(hi/px-1)*100:+.2f}%')
# also NAV week math
print()
print('agent_auto week: 1005833 -> 1002387 =', round((1002387/1005833-1)*100,2),'%')
print('center_dual week: 986434.4 -> 985180.4 =', round((985180.4/986434.4-1)*100,2),'%')
mkt=1
for r in [0.9924,-0.0852,-0.0915,-2.2544]: mkt*=1+r/100
print('CSI1000 week:', round((mkt-1)*100,2),'%')
print('agent cum from 1M:', round((1002387/1e6-1)*100,2),'%')
print('cd same window (from 0904):', round((985180.4/1019914-1)*100,2),'%')
