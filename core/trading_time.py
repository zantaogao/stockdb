#!/usr/bin/env python3
"""A股交易时段统一判定（2026-08-02 用户铁律）
交易时段: 上午 9:30-11:30, 下午 13:00-15:00
非交易时段禁止交易, 适用于所有账户（策略模拟账户 + 主账户盘中链路）。
所有产生买卖的脚本必须调用本模块, 禁止各自写时段判断（防止口径不一致）。
"""
from datetime import datetime


def in_trading_session(now: datetime = None) -> bool:
    """当前是否在 A股交易时段内。
    - 上午 9:30:00 - 11:30:59
    - 下午 13:00:00 - 15:00:59
    """
    now = now or datetime.now()
    h, m = now.hour, now.minute
    if (h == 9 and m >= 30) or h == 10 or (h == 11 and m <= 30):
        return True
    if h == 13 or h == 14 or (h == 15 and m == 0):
        return True
    return False


def session_label(now: datetime = None) -> str:
    """返回时段描述（用于日志）"""
    now = now or datetime.now()
    return "交易时段" if in_trading_session(now) else "非交易时段"
