"""最终验证：重算后的 fusion_3f_signals（新方向）8/3-8/7 IC"""
import sqlite3, duckdb
import numpy as np
from scipy.stats import spearmanr

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in tdb.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
td_idx = {d: i for i, d in enumerate(tdays)}

ics = []
print(f"{'信号日':<10} {'新fusion_3f IC':<16} {'强买IC':<14} {'n'}")
for sd in ('20260803', '20260804', '20260805', '20260806', '20260807'):
    i = td_idx[sd]
    nd = tdays[i + 1]
    sig = state.execute("""
        SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals
        WHERE REPLACE(date,'-','') = ? AND fusion_3f_score IS NOT NULL
    """, (sd,)).fetchall()
    closes = {}
    for d in (sd, nd):
        for ts, c in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", [d]).fetchall():
            closes.setdefault(ts, {})[d] = float(c)
    rets, f3s, sb_rets = [], [], []
    for sc, f3, sig_ in sig:
        full = f"{sc}.SH" if sc.startswith('6') else f"{sc}.SZ"
        p = closes.get(full)
        if not p or sd not in p or nd not in p:
            continue
        ret = p[nd] / p[sd] - 1
        rets.append(ret); f3s.append(f3)
        if sig_ == '强买':
            sb_rets.append(ret)
    ic = spearmanr(f3s, rets)[0]
    ics.append(ic)
    print(f'{sd:<10} {ic:+.4f}          {np.mean(sb_rets)*100:+.2f}%      {len(rets)}')

print(f'\n新 fusion_3f 5日均值 IC: {np.mean(ics):+.4f}（修正前 -0.117）')
tdb.close(); state.close()
