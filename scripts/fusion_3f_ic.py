#!/usr/bin/env python3
"""计算三因子融合评分的 Rank IC 并写入 factor_ic_roll"""
import sys, sqlite3, numpy as np, duckdb
from pathlib import Path
from datetime import datetime
from scipy.stats import spearmanr

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'signals.db'  # v2温层
TUSHARE_DB = BASE / 'tushare.db'

def code_to_ts(code):
    c = str(code)
    return f"{c}.SH" if c.startswith(('6','68','9')) else f"{c}.SZ"

def main():
    today = datetime.now().strftime('%Y%m%d')
    
    # 读三因子融合评分日期列表（按日分组，有足够样本），回退选择有下一个交易日的最近日期
    state = sqlite3.connect(str(STATE_DB), timeout=10)
    date_rows = state.execute("""
        SELECT REPLACE(date, '-', ''), COUNT(*)
        FROM fusion_3f_signals
        WHERE fusion_3f_score > 0
        GROUP BY REPLACE(date, '-', '')
        ORDER BY 1 DESC
    """).fetchall()
    if not date_rows:
        print("fusion_3f_signals 表为空")
        state.close()
        return
    state.close()

    # 从最近日期往前找：最新日期若当天无下一个交易日（如当日评分刚写入），
    # 回退到上一个有下一个交易日的日期，避免当日 IC 缺失（同 ic_daily.py 逻辑）
    tushare = duckdb.connect(str(TUSHARE_DB), read_only=True)
    latest, next_day = None, None
    for d, cnt in date_rows:
        if cnt < 100:
            continue
        nd = tushare.execute(
            "SELECT MIN(trade_date) FROM daily WHERE trade_date > ? AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')",
            (d,)
        ).fetchone()[0]
        if nd:
            latest, next_day = d, nd
            break
    if not latest:
        print("找不到有下一个交易日的三因子融合评分日期")
        tushare.close()
        return

    print(f"最新日期: {latest}, 次日: {next_day}")

    state = sqlite3.connect(str(STATE_DB), timeout=10)
    rows = state.execute("""
        SELECT stock_code, fusion_3f_score, date
        FROM fusion_3f_signals
        WHERE REPLACE(date, '-', '') = ?
    """, (latest,)).fetchall()
    state.close()
    
    if len(rows) < 100:
        print(f"三因子融合数据不足: {len(rows)}")
        return
    
    # 按日期分组，取最新一天
    by_date = {}
    for code, score, dt in rows:
        d = str(dt)[:10].replace('-', '')
        if d not in by_date:
            by_date[d] = []
        if score and score > 0:
            by_date[d].append((code, float(score)))
    
    if not by_date:
        print("无有效三因子融合数据")
        return
    
    latest_date = sorted(by_date.keys())[-1]
    items = by_date[latest_date]
    print(f"最新日期: {latest_date}, 样本: {len(items)}")
    print(f"次日: {next_day}")
    
    codes = [item[0] for item in items]
    ts_codes = [code_to_ts(c) for c in codes]
    ph = ','.join(['?'] * len(ts_codes))
    
    # 当日价格
    today_prices = {}
    rows_t = tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})",
        (latest_date,) + tuple(ts_codes)
    ).fetchall()
    for r in rows_t: today_prices[r[0]] = float(r[1])
    
    # 次日价格
    next_prices = {}
    rows_n = tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})",
        (next_day,) + tuple(ts_codes)
    ).fetchall()
    for r in rows_n: next_prices[r[0]] = float(r[1])
    
    tushare.close()
    
    # 计算每只股票的次日收益率（同时保留 code 映射，避免索引错位）
    scores, returns, paired_codes = [], [], []
    for code, score in items:
        ts = code_to_ts(code)
        if ts in today_prices and ts in next_prices:
            tp = today_prices[ts]
            np_ = next_prices[ts]
            if tp > 0:
                ret = (np_ / tp - 1) * 100
                scores.append(score)
                returns.append(ret)
                paired_codes.append(code)
    
    if len(scores) < 30:
        print(f"配对样本不足: {len(scores)}")
        return
    
    ic, pval = spearmanr(scores, returns)
    median_score = np.median(scores)
    win_count = sum(1 for i in range(len(returns)) if (scores[i] > median_score) == (returns[i] > 0))
    win_rate = round(win_count / len(returns), 4)  # 小数（0-1），与 factor_ic_roll 表统一
    
    print(f"三因子融合 IC: {ic:.4f} (p={pval:.4f}), 样本: {len(scores)}, 胜率: {win_rate*100:.1f}%")
    
    # 额外计算：强买信号专属表现（按 stock_code 匹配，按当天过滤）
    state2 = sqlite3.connect(str(STATE_DB), timeout=10)
    strong_codes = {r[0] for r in state2.execute("""
        SELECT stock_code FROM fusion_3f_signals 
        WHERE REPLACE(date, '-', '') = ? AND signal = '强买'
    """, (latest_date,)).fetchall()}
    state2.close()
    
    sb_ret = [returns[i] for i in range(len(paired_codes)) if paired_codes[i] in strong_codes]
    sb_scores = [scores[i] for i in range(len(paired_codes)) if paired_codes[i] in strong_codes]
    if sb_ret and len(sb_ret) >= 10:
        sb_ic_val, _ = spearmanr(sb_scores, sb_ret)
        sb_win_rate = round(sum(1 for r in sb_ret if r > 0) / len(sb_ret), 4)  # 小数（0-1）
        sb_mean_ret = round(np.mean(sb_ret), 2)
        sb_median_ret = round(np.median(sb_ret), 2)
        print(f"强买信号: {len(sb_ret)}只, IC={sb_ic_val:.4f}, 胜率={sb_win_rate*100:.1f}%, 平均收益={sb_mean_ret}%")
    else:
        sb_ic_val, sb_win_rate, sb_mean_ret, sb_median_ret = 0, 0, 0, 0
    
    # 写入 factor_ic_roll（全市场 IC）
    state = sqlite3.connect(str(STATE_DB), timeout=10)
    state.execute("""
        INSERT OR REPLACE INTO factor_ic_roll 
        (factor_name, as_of_date, window, mean_ic, std_ic, icir, win_rate, 
         max_ic, min_ic, n_days, ret_horizon, group_name)
        VALUES (?, ?, 20, ?, 0, 0, ?, ?, ?, ?, 1, '三因子融合')
    """, (
        'fusion_3f_score', latest_date,
        round(ic, 4),
        win_rate,
        round(ic if ic > 0 else 0, 4),
        round(ic if ic < 0 else 0, 4),
        len(scores)
    ))
    
    # 额外：强买信号专属胜率（收益写入 mean_ret/median_ret，max_ic/min_ic 留给 IC 语义）
    state.execute("""
        INSERT OR REPLACE INTO factor_ic_roll 
        (factor_name, as_of_date, window, mean_ic, std_ic, icir, win_rate, 
         max_ic, min_ic, n_days, ret_horizon, group_name, mean_ret, median_ret)
        VALUES (?, ?, 20, ?, 0, 0, ?, NULL, NULL, ?, 1, '三因子融合', ?, ?)
    """, (
        'fusion_3f_强买', latest_date,
        round(sb_ic_val, 4),
        sb_win_rate,
        len(sb_ret) if 'sb_ret' in dir() else 0,
        sb_mean_ret,
        sb_median_ret
    ))
    state.commit()
    state.close()
    print(f"已写入 factor_ic_roll → fusion_3f_score (IC={ic:.4f}) + fusion_3f_强买 (胜率={sb_win_rate}%)")

if __name__ == '__main__':
    main()
