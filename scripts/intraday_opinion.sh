#!/bin/bash
# 盘中意见层-实时意见（2026-08-30 上线）：交易时段每10分钟，只读咨询不下单
cd /Users/zantao/.hermes/stockdb && /usr/bin/python3 -B scripts/intraday_opinion.py 2>&1