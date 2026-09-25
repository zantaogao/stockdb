"""重算 factor_ic_roll 的 fusion 行（8/3-8/7，reg10 方向修正后的新信号）
按 fusion_3f_ic.py 同格式：fusion_3f_score(全市场IC) + fusion_3f_强买(胜率/收益)"""
import sqlite3, duckdb
import numpy as np
from scipy.stats import spearmanr

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in tdb.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
td_idx = {d: i for i, d in enumerate(tdays)}

for sd in ('20260803', '20260804', '20260805', '20260806', '20260807'):
    nd = tdays[td_idx[sd] + 1]
    rows = state.execute("""
        SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals
        WHERE REPLACE(date,'-','') = ? AND fusion_3f_score IS NOT NULL
    """, (sd,)).fetchall()
    closes = {}
    for d in (sd, nd):
        for ts, c in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", [d]).fetchall():
            closes.setdefault(ts, {})[d] = float(c)
    scores, rets, sb_ret, sb_scores = [], [], [], []
    for sc, f3, sig in rows:
        full = f"{sc}.SH" if sc.startswith('6') else f"{sc}.SZ"
        p = closes.get(full)
        if not p or sd not in p or nd not in p:
            continue
        ret = p[nd] / p[sd] - 1
        scores.append(f3); rets.append(ret)
        if sig == '强买':
            sb_ret.append(ret); sb_scores.append(f3)
    ic = spearmanr(scores, rets)[0]
    pval = spearmanr(scores, rets)[1]
    win_rate = round(sum(1 for r in rets if r > 0) / len(rets), 4)
    sb_ic = spearmanr(sb_scores, sb_ret)[0] if len(sb_scores) > 3 and len(sb_ret) > 3 else 0
    sb_win = round(sum(1 for r in sb_ret if r > 0) / len(sb_ret), 4) if sb_ret else 0
    sb_mean = round(np.mean(sb_ret) * 100, 2) if sb_ret else 0
    sb_med = round(np.median(sb_ret) * 100, 2) if sb_ret else 0

    state.execute("""INSERT OR REPLACE INTO factor_ic_roll
        (factor_name, as_of_date, window, mean_ic, std_ic, icir, win_rate,
         max_ic, min_ic, n_days, ret_horizon, group_name)
        VALUES (?, ?, 20, ?, 0, 0, ?, ?, ?, ?, 1, '三因子融合')""",
        ('fusion_3f_score', sd, round(ic, 4), win_rate,
         round(ic if ic > 0 else 0, 4), round(ic if ic < 0 else 0, 4), len(scores)))
    state.execute("""INSERT OR REPLACE INTO factor_ic_roll
        (factor_name, as_of_date, window, mean_ic, std_ic, icir, win_rate,
         max_ic, min_ic, n_days, ret_horizon, group_name, mean_ret, median_ret)
        VALUES (?, ?, 20, ?, 0, 0, ?, NULL, NULL, ?, 1, '三因子融合', ?, ?)""",
        ('fusion_3f_强买', sd, round(sb_ic, 4), sb_win, len(sb_ret), sb_mean, sb_med))
    state.commit()
    print(f'{sd}: 全市场IC={ic:+.4f} 胜率={win_rate*100:.0f}% | 强买 {len(sb_ret)}只 均收益={sb_mean:+.2f}%')

state.close(); tdb.close()
print('✅ factor_ic_roll fusion 行重算完成')
