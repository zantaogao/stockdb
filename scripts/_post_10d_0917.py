#!/usr/bin/env python3
# 10d独立榜10票日线指标 + 尾盘诱多组次日表现实测（只读）
import duckdb, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
TU = duckdb.connect('tushare.db', read_only=True)

def metrics(ts):
    rows = TU.execute("SELECT trade_date,close,pct_chg,vol,high,low FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 30", [ts]).fetchall()
    if not rows: return 'NOROW'
    rows = list(reversed(rows))
    closes=[r[1] for r in rows]
    ma10=sum(closes[-10:])/10; ma20=sum(closes[-20:])/20
    sd=(sum((x-ma20)**2 for x in closes[-20:])/20)**0.5
    up=ma20+2*sd; dn=ma20-2*sd; last=closes[-1]
    hi20=max(r[4] for r in rows[-20:]); hi30=max(r[4] for r in rows)
    vol5=sum(r[3] for r in rows[-6:-1])/5
    chg5=(closes[-1]/closes[-6]-1)*100
    updays=sum(1 for r in rows[-5:] if r[2]>0)
    # gap today
    gap = (rows[-1][5] > rows[-2][4]) if len(rows)>1 else False
    return dict(d1=rows[-1][2], ma20dev=round((last/ma20-1)*100,1),
        boll=round((last-dn)/(up-dn)*100,0) if up>dn else 50,
        d20hi=round((last/hi20-1)*100,1), chg5=round(chg5,1),
        updays=updays, volratio=round(rows[-1][3]/vol5,2) if vol5 else 0,
        close=last, gapup=gap, ma10=round(ma10,2))

print('== 10d独立榜 top10 ==')
for ts,nm in [('301390.SZ','经纬股份'),('000930.SZ','中粮科技'),('600103.SH','青山纸业'),
 ('603999.SH','读者传媒'),('002349.SZ','精华制药'),('601949.SH','中国出版'),
 ('603230.SH','内蒙新华'),('603823.SH','百合花'),('603226.SH','菲林格尔'),('688300.SH','联瑞新材')]:
    print(nm, ts, metrics(ts))

print('== 0917尾盘诱多组 次日(今)实测 ==')
for ts,nm in [('301133.SZ','金钟股份'),('688175.SH','高凌信息'),('301011.SZ','华立科技'),
 ('300970.SZ','华绿生物'),('605056.SH','咸亨国际')]:
    rows = TU.execute("SELECT trade_date,close,pct_chg FROM daily WHERE ts_code>='20260916' AND ts_code=? ORDER BY trade_date", [ts]).fetchall()
    # need by ts filter wrong col order; redo
    rows = TU.execute("SELECT trade_date,close,pct_chg FROM daily WHERE ts_code=? AND trade_date>='20260916' ORDER BY trade_date", [ts]).fetchall()
    print(nm, ts, rows)

print('== 0917低吸观察组 次日(今)实测 ==')
for ts,nm in [('301093.SZ','华兰股份'),('301503.SZ','智迪科技'),('300876.SZ','蒙泰高新'),
 ('688788.SH','科思科技'),('300668.SZ','杰恩股份')]:
    rows = TU.execute("SELECT trade_date,close,pct_chg FROM daily WHERE ts_code=? AND trade_date>='20260916' ORDER BY trade_date", [ts]).fetchall()
    print(nm, ts, rows)
