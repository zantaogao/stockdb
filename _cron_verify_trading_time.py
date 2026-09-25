#!/usr/bin/env python3
"""验证 8/7 15:00:34 写入时刻的交易时段判定 2026-08-08"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))
from core.trading_time import in_trading_session

# cron '*/10 9-15' 在 15:00:00 触发, 引擎启动+守卫判定在 15:00:0x
for t in ['15:00:00', '15:00:10', '15:00:30', '15:00:34', '15:00:40', '15:01:00']:
    hh, mm, ss = map(int, t.split(':'))
    r = in_trading_session(hour=hh, minute=mm, second=ss)
    print(f'  {t} → 交易时段: {r}')

print()
print('结论判定: 8/7 15:00:34 写入 =', '交易时段内 ✅' if in_trading_session(hour=15, minute=0, second=34) else '非交易时段 ❌')
