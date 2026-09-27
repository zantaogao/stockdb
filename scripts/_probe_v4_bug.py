import sys, time
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
from core.db import get_tushare_db
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data
conn = get_tushare_db()
import numpy as np
for ts, code in [('600508.SH','600508'), ('001225.SZ','001225')]:
    rows = conn.execute(f"SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount FROM daily WHERE ts_code='{ts}' ORDER BY trade_date").fetchall()
    print(ts, 'rows:', len(rows), 'first:', str(rows[0][0]), 'last:', str(rows[-1][0]))
    closes=[float(r[1]) for r in rows]; highs=[float(r[3]) for r in rows]; lows=[float(r[4]) for r in rows]
    pcts=[float(r[5])/100 for r in rows]; vols=[float(r[6]) for r in rows]; dates=[str(r[0]) for r in rows]
    adj = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",[ts]).fetchall()
    ac,ah,al = apply_forward_adjust(closes,highs,lows,adj)
    info = load_index_data().get(get_board_index(code))
    i = len(rows)-11; d = dates[i]
    vr = conn.execute("SELECT pe_ttm,pb,total_mv FROM daily_basic WHERE ts_code=? AND trade_date=?", [ts,d]).fetchone()
    print('  i=',i,'date=',d,'val_row=',vr)
    got = [info['dict'].get(x) for x in dates[max(0,i-20):i+1]] if info else []
    idx_c = np.array([g for g in got if g is not None], dtype=float) if all(g is not None for g in got) else None
    import numpy as np
    vd = {}
    if vr:
        pe,pb,mv = vr
        if pe and float(pe)>0: vd['ep']=1.0/float(pe)
        if pb and float(pb)>0: vd['bp']=1.0/float(pb)
        if mv and float(mv)>0: vd['ln_cap']=np.log(float(mv))
    f38 = compute_features(ac[i-60:i+1],ah[i-60:i+1],al[i-60:i+1],vols[i-60:i+1],pcts[i-60:i+1],idx_c,vd)
    if f38 is not None:
        PV = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
        f31 = [float(f38[j]) for j in PV]
        print('  f17/18/19/20/21/22 =', [round(f31[17],4), round(f31[18],4), round(f31[19],4), round(f31[20],4), round(f31[21],4), round(f31[22],4)])
        c10 = conn.execute("SELECT close FROM daily WHERE ts_code=? AND trade_date=?", [ts, dates[i+10]]).fetchone()
        print('  label date', dates[i+10], 'close', c10, 'y10=', (float(c10[0])/ac[i]-1)*100)
