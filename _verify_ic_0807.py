"""独立复算 ic_daily 8/7 行（signal_history 8/7 评分 vs 8/10 收益）"""
import sqlite3, duckdb
import numpy as np

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# 8/7 信号
sig = state.execute("""
    SELECT stock_code, fusion_score, reg10, reg20, reg40, final_score
    FROM signal_history WHERE REPLACE(date,'-','')='20260807'
""").fetchall()
print(f'8/7 信号: {len(sig)} 条')

# 8/7 和 8/10 收盘
prices = {}
for d in ('20260807', '20260810'):
    for ts, c in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", [d]).fetchall():
        prices.setdefault(ts, {})[d] = float(c)

rets, fus, r10, r20, r40 = [], [], [], [], []
for sc, fu, r1, r2, r4, fin in sig:
    full = f"{sc}.SH" if sc.startswith('6') else f"{sc}.SZ"
    p = prices.get(full)
    if not p or '20260807' not in p or '20260810' not in p:
        continue
    ret = p['20260810'] / p['20260807'] - 1
    rets.append(ret); fus.append(fu); r10.append(r1); r20.append(r2); r40.append(r4)

print(f'配对样本: {len(rets)}')
for name, arr in [('fusion', fus), ('reg10', r10), ('reg20', r20), ('reg40', r40), ('final', None)]:
    if arr is None:
        continue
    ic = np.corrcoef(arr, rets)[0, 1]
    print(f'  {name}: IC={ic:.4f}')

# 分组验证：fusion 高分 vs 低分在 8/10 的收益
fus_arr = np.array(fus); ret_arr = np.array(rets)
hi = ret_arr[fus_arr >= np.percentile(fus_arr, 90)]
lo = ret_arr[fus_arr <= np.percentile(fus_arr, 10)]
print(f'\nfusion 高分10%: 8/10 平均收益 {hi.mean()*100:+.2f}%')
print(f'fusion 低分10%: 8/10 平均收益 {lo.mean()*100:+.2f}%')
print(f'全市场 8/7→8/10 平均收益: {ret_arr.mean()*100:+.2f}%')
tdb.close(); state.close()
