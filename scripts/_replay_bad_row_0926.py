import sys, time, numpy as np
sys.path.insert(0, "/Users/zantao/.hermes/stockdb")
sys.path.insert(0, "/Users/zantao/.hermes/stockdb/scripts")
from core.db import get_tushare_db
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data

conn = get_tushare_db()
stocks = [r[0] for r in conn.execute(
    "SELECT symbol FROM stock_basic WHERE market != '北交所' AND (name NOT LIKE '%ST%' OR name IS NULL) "
    "AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%' AND symbol NOT LIKE '92%'").fetchall()]
cal = [str(r[0]) for r in conn.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20220101' ORDER BY 1").fetchall()]
cal_idx = {d: i for i, d in enumerate(cal)}
idx_data = load_index_data()
PV = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
t0 = time.time(); n10 = 0
for ci, code in enumerate(stocks):
    ts = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    rows = conn.execute(f"SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount FROM daily WHERE ts_code='{ts}' AND trade_date >= '20220101' ORDER BY trade_date").fetchall()
    if len(rows) < 71: continue
    closes = [float(r[1]) for r in rows]; highs = [float(r[3]) for r in rows]; lows = [float(r[4]) for r in rows]
    pcts = [float(r[5])/100 for r in rows]; vols = [float(r[6]) for r in rows]; dates = [str(r[0]) for r in rows]
    adj = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date", [ts]).fetchall()
    ac, ah, al = apply_forward_adjust(closes, highs, lows, adj)
    bi = get_board_index(code); info = idx_data.get(bi)
    lab = {str(r[0]): float(r[1]) for r in conn.execute(f"SELECT trade_date, close FROM daily WHERE ts_code='{ts}' AND trade_date >= '20220101'").fetchall()}
    for i in range(60, len(rows)-10):
        d = dates[i]; di = cal_idx.get(d)
        if di is None or di < 20: continue
        got = [info['dict'].get(cal[k]) for k in range(di-20, di+1)] if info else [None]
        idx_c = np.array(got, dtype=float) if all(g is not None for g in got) else None
        vr = conn.execute("SELECT pe_ttm,pb,total_mv FROM daily_basic WHERE ts_code=? AND trade_date=?", [ts, d]).fetchone()
        vd = {}
        if vr:
            pe, pb, mv = vr
            if pe and float(pe) > 0: vd['ep'] = 1.0/float(pe)
            if pb and float(pb) > 0: vd['bp'] = 1.0/float(pb)
            if mv and float(mv) > 0: vd['ln_cap'] = np.log(float(mv))
        f38 = compute_features(ac[i-60:i+1], ah[i-60:i+1], al[i-60:i+1], vols[i-60:i+1], pcts[i-60:i+1], idx_c, vd)
        if f38 is None: continue
        if len(f38) != 38:
            print(f"BAD_LEN code={code} date={d} len={len(f38)}", flush=True); continue
        arr = np.empty(31, dtype=object)
        for j in range(31):
            arr[j] = f38[PV[j]]
        for j in range(31):
            v = arr[j]
            if np.ndim(v) != 0:
                print(f"BAD_SCALAR code={code} date={d} j={j} type={type(v)} ndim={np.ndim(v)}", flush=True)
        if lab.get(dates[i+10]) is None: continue
        n10 += 1
    if (ci+1) % 500 == 0:
        print(f"  {ci+1}/{len(stocks)} n10={n10} {time.time()-t0:.0f}s", flush=True)
print("REPLAY_DONE", n10, flush=True)
