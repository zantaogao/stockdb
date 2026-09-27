"""生产链 ex 口径终裁（2026-09-26，_0925 实跑日期）：
对真实生产函数 compute_449d_features 直接喂料，回显 ex 维实际值，与三种假设对拍：
  H1 生产=板块指数截断到当日锚（=现行样本口径）
  H2 生产=板块指数全历史尾部锚（pos_end=len-1）
  H3 生产=上证同期锚（docstring 本意）
"""
import sys; sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts'); sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
import duckdb, numpy as np
from feat_tushare import load_index_data, get_board_index, compute_features

idx_full = load_index_data()
conn = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# 生产 compute_449d_features 原样解包（r[0]=date r[1]=close r[3]=high r[4]=low r[5]=pct r[6]=vol），
# 从 stock_daily 取（与生产 daily_sql 同表），feed 给 compute_features（与生产 224 行同调用）。
for ts in ['688036.SH', '300750.SZ', '600519.SH']:
    code = ts.split('.')
    code_short = ts.split('.')[0]
    code_dash = code_short + '.' + ts.split('.')[1]
    rows = conn.execute(
        "SELECT date, close, open, high, low, COALESCE(change_pct,0), volume "
        "FROM stock_daily WHERE stock_code=? ORDER BY date DESC LIMIT 120",
        [code_short]).fetchall()
    rows = rows[::-1]
    closes = [float(r[1]) for r in rows]
    highs = [float(r[3]) for r in rows]
    lows = [float(r[4]) for r in rows]
    vols = [float(r[6]) if r[6] else 0.0 for r in rows]
    pcts = [float(r[5]) / 100.0 if r[5] else 0.0 for r in rows]
    feat = compute_features(closes, highs, lows, vols, pcts, idx_full, {})
    ex_prod = feat[23], feat[24], feat[25]
    chg5 = closes[-1]/closes[-6]-1
    bi = get_board_index(code_short); sub = idx_full[bi]['dict']; sd = sorted(sub)
    all_dates = sorted({d for v in idx_full.values() for d in v['dict']})
    h1 = chg5 - (sub[sd[-1]]/sub[sd[-6]]-1)
    h2 = chg5 - (sub[all_dates[-1]]/sub[all_dates[-6]]-1)
    print(f"{ts}: 生产ex5={ex_prod[0]:+.5f} ex10={ex_prod[1]:+.5f} ex20={ex_prod[2]:+.5f} | 板块={bi}")
    print(f"   H1(板块截断锚)={h1:+.5f}  H2(板块全历史尾锚)={h2:+.5f}")
conn.close()

