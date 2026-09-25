"""验证三因子融合的 ma_decay/flow_alpha/vol_adj 方向（8/3-8/7 次日 Spearman IC）
引擎当前方向：ma_z=+（ma_decay高→高分）、flow_z=+（flow_alpha高→高分）、vol_z=-（vol_adj低→高分）"""
import sqlite3, duckdb
import numpy as np
from scipy.stats import spearmanr

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in tdb.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
td_idx = {d: i for i, d in enumerate(tdays)}

print(f"{'信号日':<10} {'ma_decay':<10} {'flow_alpha':<10} {'vol_adj':<10} {'市场':<8}")
for sd in ('20260803', '20260804', '20260805', '20260806', '20260807'):
    i = td_idx[sd]
    nd = tdays[i + 1]
    rows = state.execute("""
        SELECT f.stock_code, f.ma_decay, f.flow_alpha, f.vol_adj FROM fusion_3f_signals f
        WHERE REPLACE(f.date,'-','') = ?
    """, (sd,)).fetchall()
    closes = {}
    for d in (sd, nd):
        for ts, c in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", [d]).fetchall():
            closes.setdefault(ts, {})[d] = float(c)
    rets, ma, flow, vol = [], [], [], []
    for sc, m, f, v in rows:
        full = f"{sc}.SH" if sc.startswith('6') else f"{sc}.SZ"
        p = closes.get(full)
        if not p or sd not in p or nd not in p or m is None or f is None or v is None:
            continue
        rets.append(p[nd] / p[sd] - 1); ma.append(m); flow.append(f); vol.append(v)
    r = np.mean(rets)
    print(f'{sd:<10} {spearmanr(ma, rets)[0]:+.3f}      {spearmanr(flow, rets)[0]:+.3f}      {spearmanr(vol, rets)[0]:+.3f}      {r*100:+.2f}%')

print('\n判据: 引擎 ma_z/flow_z 用正方向(因子高→高分), vol_z 用负方向(因子低→高分)')
print('若因子与收益正相关且引擎取正 → 方向对; 负相关却取正(或反之) → 方向反')
tdb.close(); state.close()
