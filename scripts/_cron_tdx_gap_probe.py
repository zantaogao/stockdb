#!/usr/bin/env python3
"""探测：1) 残缺日在 min1_archive 里的覆盖  2) pytdx 服务器端1分钟线最早日期"""
import sys, duckdb
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from pytdx.hq import TdxHq_API

GAPS = [20260812, 20260813, 20260814, 20260817, 20260818, 20260819, 20260820, 20260821, 20260824, 20260825, 20260826, 20260827, 20260828, 20260831]

a = duckdb.connect('/Users/zantao/.hermes/stockdb/tdx_archive.db', read_only=True)
have = dict(a.execute(f"SELECT date, COUNT(DISTINCT code) FROM min1_archive WHERE date IN ({','.join(map(str,GAPS))}) GROUP BY date").fetchall())
print("=== min1_archive 覆盖 ===")
for d in GAPS:
    print(d, have.get(d, 0), "股", "← 本地可补" if have.get(d, 0) > 4000 else "")
a.close()

print("=== pytdx 服务器端探测 (000001.SZ) ===")
api = TdxHq_API()
for srv in [('218.75.126.9', 7709), ('115.238.90.165', 7709)]:
    try:
        if not api.connect(*srv, time_out=5):
            print(srv, "连接失败"); continue
        earliest = None
        for pages in range(1, 6):  # 最多翻5页×800条≈4000根≈17个交易日
            bars = api.get_security_bars(8, 0, '000001', (pages-1)*800, 800)
            if not bars: break
            d0 = str(bars[0].get('datetime', '')).replace('-', '').replace(':', '').replace(' ', '')[:8]
            if d0.isdigit():
                earliest = min(earliest, int(d0)) if earliest else int(d0)
            if len(bars) < 800: break
        print(srv, "最早1分钟线:", earliest)
        api.disconnect()
    except Exception as e:
        print(srv, "ERR", e)