"""推算 ic_window 各窗口首条数据回填日期（2026-08-10）"""
import duckdb
from datetime import datetime

db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
days = [str(r[0]) for r in db.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
db.close()

sig_dates = ['20260803', '20260804', '20260805', '20260806', '20260807']
idx = {d: i for i, d in enumerate(days)}
print(f'交易日历: {len(days)} 天, 最新={days[-1]}')
for sd in sig_dates:
    if sd not in idx:
        print(f'{sd}: 不在日历'); continue
    i0 = idx[sd]
    out = []
    for off in (10, 20, 40):
        j = i0 + off
        out.append(f'w{off}→{days[j] if j < len(days) else "未到(还需%d天)" % (j - len(days) + 1)}')
    print(f'{sd} 信号日 (index {i0}, 距今天{- (len(days) - 1 - i0)} 交易日): ' + ' | '.join(out))
print()
print('今天:', datetime.now().strftime('%Y%m%d'), '= 日历 index', idx.get(datetime.now().strftime('%Y%m%d')))
