# 追加NPO观察池：华工科技000988（光模块+光芯片自研）、三安光电600703（化合物半导体/外延片，光芯片上游）
# 同口径：entry=MA10±2%回踩区，止损=MA20×0.97，score=92 pending，source=manual_npo
import sqlite3, duckdb
BASE='/Users/zantao/.hermes/stockdb'
d=duckdb.connect(BASE+'/tushare.db', read_only=True)
L=sqlite3.connect(BASE+'/ledger.db')
for suf,name in [('000988.SZ','华工科技'),('600703.SH','三安光电')]:
    g=d.execute(f"SELECT trade_date,close FROM daily WHERE ts_code='{suf}' AND trade_date>='20260815' ORDER BY trade_date").df()
    adj=d.execute(f"SELECT trade_date,adj_factor FROM adj_factor WHERE ts_code='{suf}' AND trade_date>='20260815' ORDER BY trade_date").df()
    g=g.merge(adj,on='trade_date'); g['f']=g['adj_factor']/g['adj_factor'].iloc[-1]; g['qc']=g['close']*g['f']
    ma10=g['qc'].tail(10).mean(); ma20=g['qc'].tail(20).mean(); px=g['qc'].iloc[-1]
    lo,hi=round(ma10*0.98,2),round(ma10*1.02,2); stop=round(ma20*0.97,2)
    L.execute("UPDATE watchlist SET status='archived' WHERE ts_code=? AND status='pending'", (suf,))
    L.execute("""INSERT INTO watchlist (ts_code,score,scan_date,status,created_at,entry_low,entry_high,target_price,stop_loss,source)
                 VALUES (?,92,'2026-09-19','pending',datetime('now','localtime'),?,?,?,?,'manual_npo')""",
              (suf,lo,hi,round(px*1.15,2),stop))
    print(f"{name} {suf} 现价{px:.2f} MA10={ma10:.2f} MA20={ma20:.2f} → 介入区 {lo}~{hi} 止损 {stop} (距现价 {(lo/px-1)*100:+.1f}%)")
L.commit()
print(L.execute("SELECT ts_code,entry_low,entry_high,stop_loss FROM watchlist WHERE source='manual_npo' AND status='pending'").fetchall())
L.close(); d.close()
