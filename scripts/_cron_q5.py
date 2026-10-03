import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.trade_calendar import is_trading_day
import datetime
d = datetime.date(2026, 10, 1)
for i in range(12):
    dd = d + datetime.timedelta(days=i)
    print(dd.isoformat(), 'TRADING' if is_trading_day(dd.strftime('%Y%m%d')) else 'closed')
