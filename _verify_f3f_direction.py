"""修正方向实验：reg10 取负 vs 不取负 的 fusion_3f_score IC 对比（8/3-8/7）
fusion_flip = clamp(fusion_orig + 10*(reg10-center)/scale, 0, 100)
center/scale = 当日 reg10 稳健统计（中位数 / 1.4826*MAD，1%-99% 截断，与 fusion_3f_engine.run 同口径）"""
import sqlite3, duckdb
import numpy as np
from scipy.stats import spearmanr

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in tdb.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
td_idx = {d: i for i, d in enumerate(tdays)}

def robust_stats(vals):
    v = np.array(vals, dtype=float)
    lo, hi = np.percentile(v, 1), np.percentile(v, 99)
    c = v[(v >= lo) & (v <= hi)]
    med = np.median(c)
    mad = np.median(np.abs(c - med))
    return med, 1.4826 * mad if mad > 0 else 1.0

print(f"{'信号日':<10} {'reg10方向':<14} {'fusion_3f现状':<14} {'fusion_3f修正':<14} {'n':<6} {'改善'}")
for sd in ('20260803', '20260804', '20260805', '20260806', '20260807'):
    i = td_idx[sd]
    if i + 1 >= len(tdays):
        continue
    nd = tdays[i + 1]
    sig = state.execute("""
        SELECT s.stock_code, s.reg10, f.fusion_3f_score
        FROM signal_history s
        JOIN fusion_3f_signals f ON f.stock_code = s.stock_code AND REPLACE(f.date,'-','') = ?
        WHERE REPLACE(s.date,'-','') = ? AND s.reg10 IS NOT NULL AND f.fusion_3f_score IS NOT NULL
    """, (sd, sd)).fetchall()
    closes = {}
    for d in (sd, nd):
        for ts, c in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", [d]).fetchall():
            closes.setdefault(ts, {})[d] = float(c)
    rets, r10s, f3fs, f3f_flips = [], [], [], []
    center, scale = robust_stats([r[1] for r in sig])
    for sc, r10, f3f in sig:
        full = f"{sc}.SH" if sc.startswith('6') else f"{sc}.SZ"
        p = closes.get(full)
        if not p or sd not in p or nd not in p:
            continue
        rets.append(p[nd] / p[sd] - 1)
        r10s.append(r10); f3fs.append(f3f)
        f3f_flips.append(max(0.0, min(100.0, f3f + 10.0 * (r10 - center) / scale)))
    ic_r10 = spearmanr(r10s, rets)[0]
    ic_f3f = spearmanr(f3fs, rets)[0]
    ic_flip = spearmanr(f3f_flips, rets)[0]
    print(f"{sd:<10} {ic_r10:+.4f}        {ic_f3f:+.4f}        {ic_flip:+.4f}        {len(rets):<6} {ic_flip-ic_f3f:+.4f}")

tdb.close(); state.close()
