#!/usr/bin/env python3
"""输出 TRADING_DAY=1/0 —— 给 agent-prompt 型 cron 任务当日历硬闸用。
退出码恒为 0（=0 不算任务失败，由 prompt 自己按输出静默收尾）。"""
import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.trade_calendar import is_trading_day
print('TRADING_DAY=' + ('1' if is_trading_day() else '0'))
