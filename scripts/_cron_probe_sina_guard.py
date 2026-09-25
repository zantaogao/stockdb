#!/usr/bin/env python3
"""cron 巡检: 复现 guard 误判 — 直连 Sina 探20次，统计失败率 + 实测 guard 判定"""
import sys, time
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.prices import _fetch_sina, fetch_price_live, fetch_prices_batch, _price_cache
from core.trading_time import in_trading_session

print("session now:", in_trading_session())
fails = 0
N = 20
for i in range(N):
    d = _fetch_sina(['000001'])
    ok = bool(d) and d.get('000001', {}).get('price')
    if not ok:
        fails += 1
    print(f"  #{i+1} raw={d}")
    time.sleep(0.5)
print(f"_fetch_sina 直连: {N - fails}/{N} 成功, 失败 {fails}")

# guard 判定复现（清缓存，走 cache 路径）
for i in range(5):
    _price_cache.clear()
    px, chg = fetch_price_live('000001')
    trip = (not px) or abs(chg) < 0.0001
    print(f"  guard试 #{i+1}: px={px} chg={chg} -> {'跳过(误判)' if trip else '正常放行'}")
    time.sleep(2)
