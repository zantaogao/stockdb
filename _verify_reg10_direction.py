"""方向实验：reg10 在 fusion_3f 里取负 vs 不取负 的 IC 对比（8/3-8/7）
判定 reg10 v3 真实方向 + 三因子融合方向错误的量化影响"""
import sqlite3, duckdb
import numpy as np

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# 交易日序列（找次日）
tdays = [str(r[0]) for r in tdb.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
td_idx = {d: i for i, d in enumerate(tdays)}

for sd in ('20260803', '20260804', '20260805', '20260806', '20260807'):
    i = td_idx[sd]
    if i + 1 >= len(tdays):
        continue
    nd = tdays[i + 1]
    # 当日信号：reg10, fusion_3f_score
    sig = state.execute("""
        SELECT s.stock_code, s.reg10, f.fusion_3f_score
        FROM signal_history s
        LEFT JOIN fusion_3f_signals f ON f.stock_code = s.stock_code AND REPLACE(f.date,'-','') = ?
        WHERE REPLACE(s.date,'-','') = ? AND s.reg10 IS NOT NULL
    """, (sd, sd)).fetchall()
    # 当日+次日收盘
    closes = {}
    for d in (sd, nd):
        for ts, c in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", [d]).fetchall():
            closes.setdefault(ts, {})[d] = float(c)
    rets, reg10s, f3fs = [], [], []
    for sc, r10, f3f in sig:
        full = f"{sc}.SH" if sc.startswith('6') else f"{sc}.SZ"
        p = closes.get(full)
        if not p or sd not in p or nd not in p:
            continue
        if f3f is None or r10 is None:
            continue
        rets.append(p[nd] / p[sd] - 1)
        reg10s.append(r10)
        f3fs.append(f3f)
    rets, reg10s, f3fs = map(np.array, (rets, reg10s, f3fs))
    ic_r10 = np.corrcoef(reg10s, rets)[0, 1]
    ic_f3f = np.corrcoef(f3fs, rets)[0, 1]
    print(f'{sd}→{nd}: reg10 IC={ic_r10:+.4f} | fusion_3f(现状) IC={ic_f3f:+.4f} | n={len(rets)}')

# 汇总
print('\n结论判据: reg10 IC 为正 = reg10 v3 正向模型(高分看涨); 三因子融合现状 IC 若被 reg10 拖累则方向用反')
tdb.close(); state.close()
