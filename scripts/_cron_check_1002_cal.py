import sys, datetime
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core import trade_calendar as tc
print('source funcs:', [x for x in dir(tc) if not x.startswith('_')])
try:
    print('is_trading_day(2026-10-02):', tc.is_trading_day(datetime.date(2026,10,2)))
except Exception as e:
    print('is_trading_day err:', type(e).__name__, e)
try:
    tc.assert_trading_day()
    print('assert: TRADING DAY')
except SystemExit as e:
    print('assert: NON-TRADING, exit msg:', e)
except Exception as e:
    print('assert err:', type(e).__name__, e)
