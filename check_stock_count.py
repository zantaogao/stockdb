#!/usr/bin/env python3
import duckdb
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
c = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
rows = c.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
print(f"stock_basic: {rows} 只股票")

# 检查 state.db 的 signal_history 表是否存在
try:
    s = duckdb.connect(str(BASE / 'state.db'), read_only=False)
    s.execute("CREATE TABLE IF NOT EXISTS signal_history (date DATE, stock_code VARCHAR, stock_name VARCHAR, industry VARCHAR, fusion_score DOUBLE, reg20 DOUBLE, reg40 DOUBLE, reg10 DOUBLE, gtja_score DOUBLE, deviation120 DOUBLE, final_score DOUBLE, fusion_avg DOUBLE, cls27_prob DOUBLE, lstm DOUBLE, reg_pred DOUBLE, reg10_pred DOUBLE, reg40_pred DOUBLE, is_limit_up BOOLEAN)")
    print("signal_history 表已就绪")
    s.close()
except Exception as e:
    print(f"state.db 错误：{e}")

c.close()
