#!/usr/bin/env python3
"""验证增量窗口（特征日 5/15-6/11）的 40 日收益分布是否合理"""
import sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))
from core.db import get_tushare_db
from feat_tushare import apply_forward_adjust

conn = get_tushare_db()

# 抽样 100 只，计算 5/15~6/11 特征日的 40 日收益（前复权）
stocks = [r[0] for r in conn.execute("""
    SELECT symbol FROM stock_basic WHERE market != '北交所'
    AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%' LIMIT 100
""").fetchall()]

all_rets = []
for code in stocks:
    ts = f"{code}.SH" if code.startswith(('6','9')) else f"{code}.SZ"
    rows = conn.execute("""
        SELECT trade_date, close, open, high, low FROM daily WHERE ts_code=?
        AND trade_date >= '20260420' ORDER BY trade_date
    """, [ts]).fetchall()
    if len(rows) < 60:
        continue
    closes = [float(r[1]) for r in rows]
    highs = [float(r[3]) for r in rows]
    lows = [float(r[4]) for r in rows]
    dates = [str(r[0]) for r in rows]
    adj_rows = conn.execute(
        "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date", [ts]).fetchall()
    adj_c, adj_h, adj_l = apply_forward_adjust(closes, highs, lows, adj_rows)
    # 找 5/15 和 6/11 的特征日，各算 40 日收益
    for target in ('20260515', '20260611'):
        idx = None
        for i, d in enumerate(dates):
            if d >= target:
                idx = i
                break
        if idx is None or idx + 40 >= len(adj_c):
            continue
        ret = (adj_c[idx+40] / adj_c[idx] - 1) * 100
        all_rets.append(ret)

all_rets = np.array(all_rets)
print(f'样本: {len(all_rets)}')
print(f'40日收益分布: mean={all_rets.mean():+.2f}% median={np.median(all_rets):+.2f}% p10={np.percentile(all_rets,10):+.2f}% p90={np.percentile(all_rets,90):+.2f}%')

# 对照：市场同期（上证指数 5/15→8 月初）
idx = conn.execute("""
    SELECT date, close FROM index_daily WHERE index_code='000001'
    AND date >= '2026-05-10' AND date <= '2026-08-10' ORDER BY date
""").fetchall()
if idx:
    base = idx[0][1]
    print(f'上证: 5/12={base:.0f}')
    for d, c in idx:
        if str(d) >= '2026-06-01' and str(d) <= '2026-06-20' or str(d) >= '2026-07-15':
            print(f'  {d}: {c:.0f} ({(c/base-1)*100:+.1f}%)')
conn.close()
