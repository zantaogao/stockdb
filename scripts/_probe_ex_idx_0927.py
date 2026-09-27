# 定案: 新ex算式(个股日历pos_end-5/-10/-20为基准日) 等价模拟 vs 生产口径 ex 逐票差
import sys, sqlite3, duckdb, random, numpy as np
sys.path.insert(0,'/Users/zantao/.hermes/stockdb'); sys.path.insert(0,'/Users/zantao/.hermes/stockdb/scripts')
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data
import core.scoring as cs
conn=cs._safe_connect()
from core.scoring import _compute_ml_features

sig=sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
codes=[r[0] for r in sig.execute("SELECT stock_code FROM signal_history WHERE date='20260827' AND reg20!=0").fetchall()]
random.seed(2); sample=random.sample(codes,20)
con=duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
idx_data=load_index_data()
d_ok=[]
for code in sample:
    ts=code+'.SH' if code.startswith(('6','68','9')) else code+'.SZ'
    rows=con.execute(f"SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount FROM daily WHERE ts_code='{ts}' AND trade_date>='20220407' AND trade_date<='20260827' ORDER BY trade_date").fetchall()
    if len(rows)<121: continue
    dates=[str(r[0]) for r in rows]; closes=[float(r[1]) for r in rows]; highs_raw=[float(r[3]) for r in rows]
    lows_raw=[float(r[4]) for r in rows]; pcts=[float(r[5])/100.0 for r in rows]; volumes=[float(r[6]) for r in rows]
    af=con.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",[ts]).fetchall()
    ac,ah,al=apply_forward_adjust(closes,highs_raw,lows_raw,af)
    board=idx_data.get(get_board_index(code))
    i=len(dates)-1
    # 生产口径(=scoring现喂法): 指数全历史截至今日
    prod_idx={dd:board['dict'][dd] for dd in board['dates'] if dd.replace('-','')<=dates[i]}
    f_prod=compute_features(ac[i-59:i+1],ah[i-59:i+1],al[i-59:i+1],volumes[i-59:i+1],pcts[i-59:i+1],prod_idx,{})
    # 新算法模拟: 基准日=个股日历 i-5/i-10/i-20, 指数chg按基准日→今日, 除权日adj因子比=个股chg口径对齐
    # chg5用adj(个股复权), 指数项=idx_today/idx_base-1 (idx无除权)
    idx_now=board['dict'].get(dates[i].replace('-','')[:4]+'-'+dates[i][4:6]+'-'+dates[i][6:8])
    if idx_now is None: continue
    exn=[]
    for pos in (i-5,i-10,i-20):
        bd=dates[pos]; bdate=f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"
        ib=board['dict'].get(bdate, idx_now)
        exn.append((ac[i]/ac[pos]-1) - (idx_now/ib-1))
    d_ok.append((code, [round(v,4) for v in (f_prod[23],f_prod[24],f_prod[25])], [round(v,4) for v in exn]))
print("可对比票数:", len(d_ok))
for c,p,n in d_ok[:5]: print(c, "生产:",p,"新算式:",n)
md=[[abs(p[k]-n[k]) for c,p,n in d_ok] for k in range(3)]
print("mean|Δ|:", [round(np.mean(m),4) for m in md], "max|Δ|:", [round(max(m),4) for m in md])
