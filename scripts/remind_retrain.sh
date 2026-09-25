#!/bin/bash
# ============================================================
# 模型重训提醒 — 检查模型是否需要重新训练
# 检查项：
#   1. 模型文件年龄（训练日期距今天数）
#   2. 模型级 IC 健康度（signals.db ic_daily）
#   3. 三因子融合滚动 IC（signals.db factor_ic_roll）
# 用法：cd ~/.hermes/stockdb && scripts/remind_retrain.sh
# ============================================================
set -e
cd "$(dirname "$0")/.."   # scripts/ -> stockdb 根目录
python3 -B scripts/remind_retrain_check.py
