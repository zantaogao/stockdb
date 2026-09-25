#!/bin/bash
# 三因子融合10d评分 — 每日收盘后执行
# 先更新因子表，再跑融合评分
cd /Users/zantao/.hermes/stockdb
python3 new_factors.py 2>&1
python3 fusion_3f_engine.py 2>&1
