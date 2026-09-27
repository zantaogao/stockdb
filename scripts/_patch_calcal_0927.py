#!/usr/bin/env python3
"""一次性改造 update_tushare_api.py：日历循环 + ETF 短路（跑完可留档）"""
import re

P = '/Users/zantao/.hermes/stockdb/scripts/update_tushare_api.py'
src = open(P).read()

# 1) stk_factor 回补循环：文案修正（保留防御性 skip）
old = '                    # 2026-09-27 休市短路: 休市日 0 行是常态，先查权威日历，非交易日 skip 不重试\n'
assert old in src, 'old1'
src = src.replace(old, '                    # 2026-09-27: 回补循环节假日不重试（循环节假日来自 daily 表，防御性检查）\n', 1)

# 2) update_etf 逐代码循环 → 日历序列
old2 = '                while current <= end_date:\n                    df2 = pro.fund_daily(ts_code=c, start_date=current, end_date=current)'
assert old2 in src, 'old2'
new2 = (
"                _edays = _missing_trading_days('fund_daily', 'trade_date', current, end_date)\n"
"                if _edays is None:\n"
"                    _edays = []\n"
"                    _c2 = current\n"
"                    while _c2 <= end_date:\n"
"                        _edays.append(_c2)\n"
"                        _c2 = next_day(_c2)\n"
"                for current in _edays:\n"
"                    if current < start: continue\n"
"                    df2 = pro.fund_daily(ts_code=c, start_date=current, end_date=current)"
)
src = src.replace(old2, new2, 1)

# 3) 删 update_etf 体内旧的 current = next_day(current)
m = re.search(r'\ndef update_etf\(pro\):', src)
end = src.find('\ndef ', m.start() + 1)
seg = src[m.start():end if end > 0 else len(src)]
seg2 = seg.replace('                    current = next_day(current)\n', '')
assert seg2 != seg, 'no next_day line in etf'
src = src[:m.start()] + seg2 + src[end:]

open(P, 'w').write(src)
print('written OK')
