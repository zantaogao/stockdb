#!/bin/bash
# 一次性回补影子打分：终训样本外且特征已齐的日期（0812~0902 缺口补齐后重跑）
cd /Users/zantao/.hermes/stockdb || exit 1
for d in 20260812 20260813 20260814 20260817 20260818 20260819 20260820 20260821 20260824 20260825 20260826 20260827 20260828 20260831 20260901 20260902; do
  echo "--- $d ---"
  /usr/bin/python3 -B scripts/shadow_score_daily.py $d | tail -1
done
/usr/bin/python3 -B scripts/shadow_ic_check.py