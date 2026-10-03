# -*- coding: utf-8 -*-
"""验收回放：603257 中国瑞林 中国瑞林 买 08-07 09:30:56@66.90 / 卖 08-21 09:30:31@61.99
目的：验证 RQAlpha 分钟撮合能否复现 exec_agent 的实际成交流（开盘首窗口下单）。
口径：分钟频率，首根可用 bar(baostock bar-end 09:35) 才下单；nan bar 跳过（skill 实锤）。
"""
from rqalpha.api import order_shares, order_target_percent

CODE = '603257.XSHG'
BUY_DAY = '2026-08-07'
SELL_DAY = '2026-08-21'


def init(context):
    context.done_buy = False
    context.done_sell = False


def handle_bar(context, bar_dict):
    b = bar_dict[CODE]
    if b is None or b.close != b.close:      # nan bar（09:31-09:34 无数据）跳过
        return
    d = context.now.strftime('%Y-%m-%d')
    if d == BUY_DAY and not context.done_buy:
        order_shares(CODE, 1400)
        context.done_buy = True
        print('[REPLAY] %s %s 首bar open=%.3f close=%.3f high=%.3f low=%.3f 下单买1400' % (
            d, context.now.strftime('%H:%M:%S'), b.open, b.close, b.high, b.low))
    elif d == SELL_DAY and not context.done_sell:
        order_shares(CODE, -1400)
        context.done_sell = True
        print('[REPLAY] %s %s 首bar open=%.3f close=%.3f high=%.3f low=%.3f 下单卖1400' % (
            d, context.now.strftime('%H:%M:%S'), b.open, b.close, b.high, b.low))
