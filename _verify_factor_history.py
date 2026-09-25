"""大样本方向验证：new_factors 三因子 vs 次日收益（7/6 起全历史，逐日截面 IC 均值）
vol_adj 方向争议：引擎取负(低→高分)，8/3-8/7 实盘 4/5 天正相关 → 用历史大样本判定"""
import sqlite3, duckdb
import numpy as np
from scipy.stats import spearmanr

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in tdb.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
td_idx = {d: i for i, d in enumerate(tdays)}

# new_factors 的日期（7/6 起）
dates = [str(r[0]).replace('-', '') for r in state.execute(
    "SELECT DISTINCT date FROM new_factors ORDER BY date").fetchall()]
print(f'new_factors 历史日期: {dates[0]} ~ {dates[-1]} 共 {len(dates)} 天')

ic_ma, ic_flow, ic_vol, n_days = [], [], [], 0
for sd in dates:
    if sd not in td_idx or td_idx[sd] + 1 >= len(tdays):
        continue
    nd = tdays[td_idx[sd] + 1]
    rows = state.execute("""
        SELECT nf.stock_code, nf.ma_decay, fa.flow_alpha, va.vol_adj
        FROM new_factors nf
        JOIN flow_alpha fa ON fa.stock_code = nf.stock_code AND fa.date = nf.date
        JOIN vol_adj va ON va.stock_code = nf.stock_code AND va.date = nf.date
        WHERE REPLACE(nf.date,'-','') = ?
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
    if len(rets) < 1000:
        continue
    ic_ma.append(spearmanr(ma, rets)[0])
    ic_flow.append(spearmanr(flow, rets)[0])
    ic_vol.append(spearmanr(vol, rets)[0])
    n_days += 1

print(f'\n有效截面日: {n_days}')
for name, arr in [('ma_decay', ic_ma), ('flow_alpha', ic_flow), ('vol_adj', ic_vol)]:
    arr = np.array(arr)
    pos = (arr > 0).mean() * 100
    t = arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 and arr.std() > 0 else 0
    print(f'{name}: 日均IC={arr.mean():+.4f} 正天数占比={pos:.0f}% t={t:+.2f} p≈{2*(1-__import__("scipy").stats.t.cdf(abs(t), len(arr)-1)):.3f}')
tdb.close(); state.close()
