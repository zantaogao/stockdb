#!/usr/bin/env python3
"""造测试 CSV（模拟 PC tdx_stock_data.db 导出格式）+ 测试导入 2026-08-08"""
import sys, csv
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb' / 'scripts'))
import importlib.util
spec = importlib.util.spec_from_file_location('tdxagg', str(Path.home() / '.hermes' / 'stockdb' / 'scripts' / 'tdx_intraday_agg.py'))
tdxagg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tdxagg)

# 1. 用本地 sh600000.lc1 造 CSV（最近 2 天）
df = tdxagg.parse_lc1('/Users/zantao/.hermes/stockdb/tdx/vipdoc/sh/minline/sh600000.lc1')
recent = sorted(df['date'].unique())[-2:]
sub = df[df['date'].isin(recent)]
with open('/tmp/tdx_min1_recent.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['code', 'market', 'datetime', 'open', 'high', 'low', 'close', 'amount', 'volume'])
    for _, r in sub.iterrows():
        dt = f"{int(r['date'])} {int(r['tm']) // 60:02d}{int(r['tm']) % 60:02d}"
        w.writerow(['600000', 'sh', dt, r['open'], r['high'], r['low'], r['close'], 0, r['vol']])
print(f'测试 CSV 写好: {len(sub)} 行, 日期 {recent}')
