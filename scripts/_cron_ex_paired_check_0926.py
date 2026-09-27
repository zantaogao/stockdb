"""生产 vs 样本 ex 口径对拍（2026-09-26 定案）：
生产路径(compute_features 351-356行原样逻辑) vs 样本路径(板块子字典截断) vs 真值(个股chg5-上证chg5同期)。
"""
import sys; sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts'); sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
import duckdb
from feat_tushare import load_index_data, get_board_index

idx_data = load_index_data()
all_dates = sorted({d for v in idx_data.values() for d in v['dates']})
sh = idx_data['000001']['dict']
conn = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for code in ['688036.SH', '300750.SZ', '600519.SH']:
    rows = conn.execute(f"SELECT trade_date, close FROM daily WHERE ts_code='{code}' ORDER BY trade_date").fetchall()
    dts = [str(r[0]) for r in rows]
    lab = {str(r[0]): float(r[1]) for r in rows}
    d0 = dts[-1]
    board = get_board_index(code.split('.')[0])
    sub = idx_data[board]['dict']
    chg5 = lab[d0] / lab[dts[-6]] - 1
    # 生产口径：合并轴尾部锚定（compute_features 用 sorted(传入dict的keys) 取 pos_end=len-1）
    pe = len(all_dates) - 1
    ex_prod = chg5 - (sh[all_dates[pe]] / sh[all_dates[pe - 5]] - 1)
    # 样本口径：本板块子字典截断到 d0
    sd = sorted(d for d in sub if d <= d0)
    ex_smp = chg5 - (sub[sd[-1]] / sub[sd[-6]] - 1)
    # 真值：个股chg5 − 上证指数同期chg5（同交易日锚定）
    k = max(i for i, d in enumerate(all_dates) if d <= d0 and d in sh and all_dates[max(i-5,0)] in sh)
    # 上证最近 5 个有数据日
    shd = sorted(d for d in sh if d <= d0)
    ex_truth = chg5 - (sh[shd[-1]] / sh[shd[-6]] - 1)
    print(f'{code} 最后股票日={d0} 板块指数={board}: 生产口径={ex_prod:+.4f} 样本口径={ex_smp:+.4f} 真值(上证同期)={ex_truth:+.4f}')
conn.close()
