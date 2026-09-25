# -*- coding: utf-8 -*-
"""导出 tdx_stock_data.db 的分钟数据为 CSV（供 Mac 每日同步）
用法: python export_tdx_recent.py [days]  默认最近3天(弥补漏拉)
输出: C:/Users/zanta/tdx_min1_recent.csv / tdx_min5_recent.csv
"""
import sqlite3, csv, sys, datetime
from pathlib import Path

DB = Path(r'C:\Users\zanta\tdx_stock_data.db')
days = int(sys.argv[1]) if len(sys.argv) > 1 else 3
# datetime 格式 'YYYYMMDD HHMM'，取最近 N 个自然日（含周末缓冲）
cutoff = (datetime.datetime.now() - datetime.timedelta(days=days + 2)).strftime('%Y%m%d')

conn = sqlite3.connect(str(DB))
for tbl, out in [('min1', 'C:/Users/zanta/tdx_min1_recent.csv'),
                 ('min5', 'C:/Users/zanta/tdx_min5_recent.csv')]:
    rows = conn.execute(
        f"SELECT code, market, datetime, open, high, low, close, amount, volume "
        f"FROM {tbl} WHERE datetime >= ? ORDER BY datetime", (cutoff,)).fetchall()
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['code', 'market', 'datetime', 'open', 'high', 'low', 'close', 'amount', 'volume'])
        w.writerows(rows)
    mx = rows[-1][2] if rows else '无'
    print(f'{tbl}: {len(rows)} 行, 最新 {mx} → {out}')
conn.close()
