# 手工加入NPO观察池：太辰光/致尚科技/长芯博创/仕佳光子/源杰科技
# 口径：status=pending + score=92（进盘中意见引擎读取线 >=90，非模型分）
# entry区间=MA10下沿~MA10上沿2%（回踩低吸腿），stop=MA20×0.97（判断4的证伪线），source标手工防误清
import sqlite3, duckdb
import pandas as pd
BASE='/Users/zantao/.hermes/stockdb'
targets={'300570':'太辰光','301486':'致尚科技','300548':'长芯博创','688313':'仕佳光子','688498':'源杰科技'}
d=duckdb.connect(BASE+'/tushare.db', read_only=True)
L=sqlite3.connect(BASE+'/ledger.db')
rows=[]
for code,name in targets.items():
    suf=code+'.SZ' if code[0]=='3' or code[0]=='0' else code+'.SH'
    g=d.execute(f"SELECT trade_date,close,high FROM daily WHERE ts_code='{suf}' AND trade_date>='20260815' ORDER BY trade_date").df()
    a=d.execute(f"SELECT adj_factor FROM adj_factor WHERE ts_code='{suf}' ORDER BY trade_date DESC LIMIT 1").fetchone()[0]
    latest=d.execute(f"SELECT close,adj_factor FROM daily d2 JOIN adj_factor a2 USING(ts_code,trade_date) WHERE ts_code='{suf}' ORDER BY trade_date DESC LIMIT 1").fetchone()
    adj=d.execute(f"SELECT trade_date,adj_factor FROM adj_factor WHERE ts_code='{suf}' AND trade_date>='20260815' ORDER BY trade_date").df()
    g=g.merge(adj,on='trade_date'); g['f']=g['adj_factor']/g['adj_factor'].iloc[-1]; g['qc']=g['close']*g['f']
    ma10=g['qc'].tail(10).mean(); ma20=g['qc'].tail(20).mean(); px=g['qc'].iloc[-1]
    lo,hi=round(ma10*0.98,2),round(ma10*1.02,2); stop=round(ma20*0.97,2)
    rows.append((suf,92,'2026-09-19','pending',px,ma10,ma20,lo,hi,stop))
    print(f"{name} {suf} 现价{px:.2f} MA10={ma10:.2f} MA20={ma20:.2f} → 介入区 {lo}~{hi} 止损参考 {stop}")
# 已有 pending 同码行先归档避免 ROW_NUMBER 取到旧行
for code,_ in targets.items():
    L.execute("UPDATE watchlist SET status='archived' WHERE ts_code LIKE ? AND status='pending'", (code+'%',))
for suf,score,sd,st,px,ma10,ma20,lo,hi,stop in rows:
    L.execute("""INSERT INTO watchlist (ts_code,score,scan_date,status,created_at,entry_low,entry_high,target_price,stop_loss,source)
                 VALUES (?,?,?,?,datetime('now','localtime'),?,?,?,?,'manual_npo')""",
              (suf,score,sd,st,lo,hi,round(px*1.15,2),stop))
L.commit()
print('watchlist now:', L.execute("SELECT ts_code,score,status,entry_low,entry_high,stop_loss,source FROM watchlist WHERE source='manual_npo'").fetchall())
L.close(); d.close()
