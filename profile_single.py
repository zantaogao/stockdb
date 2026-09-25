#!/usr/bin/env python3
import time, duckdb, numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from feat_tushare import compute_features, load_index_data, load_gtja_compact, get_gtja_value
from core import db

BASE = Path.home() / '.hermes' / 'stockdb'
conn = db.get_tushare_db()

# 加载辅助数据
idx_dict = load_index_data()
gtja = load_gtja_compact()

# 取第一只股票
code = conn.execute("SELECT ts_code FROM stock_basic LIMIT 1").fetchone()[0]
code_short = code.split('.')[0]

print(f"测试股票：{code} ({code_short})")

# 计时查询 K 线
t0 = time.time()
rows = conn.execute("""
    SELECT date, close, open, high, low, COALESCE(change_pct, 0), volume, amount
    FROM stock_daily WHERE stock_code=? ORDER BY date DESC LIMIT 120
""", [code_short]).fetchall()
print(f"查询 K 线：{(time.time()-t0)*1000:.0f}ms ({len(rows)}条)")

rows = rows[::-1]
closes = [float(r[1]) for r in rows]
highs = [float(r[3]) for r in rows]
lows = [float(r[4]) for r in rows]
volumes = [float(r[6]) if r[6] else 0.0 for r in rows]
pcts = [float(r[5]) / 100.0 if r[5] else 0.0 for r in rows]
dates_str = [str(r[0])[:10].replace('-', '') for r in rows]

# 估值
val_row = conn.execute(
    "SELECT pe_ttm, pb, total_mv FROM stock_valuation WHERE stock_code=? ORDER BY date DESC LIMIT 1",
    [code_short]
).fetchone()
val_dict = {}
if val_row and val_row[0]:
    if val_row[0] and float(val_row[0]) > 0:
        val_dict['ep'] = 1.0 / float(val_row[0])
    if val_row[1] and float(val_row[1]) > 0:
        val_dict['bp'] = 1.0 / float(val_row[1])
    if val_row[2] and float(val_row[2]) > 0:
        val_dict['ln_cap'] = np.log(float(val_row[2]))

# 计时特征计算
t0 = time.time()
feat = compute_features(closes, highs, lows, volumes, pcts, idx_dict, val_dict)
print(f"计算 38 基础特征：{(time.time()-t0)*1000:.0f}ms")

# GTJA
t0 = time.time()
if gtja:
    gtja_vals = get_gtja_value(code, dates_str[-1], gtja)
else:
    gtja_vals = [0.0] * 11
print(f"获取 GTJA 因子：{(time.time()-t0)*1000:.0f}ms")

print(f"\n总计：约{(time.time()-t0)*1000:.0f}ms/只")
print(f"5868 只股票预计：{5868 * ((time.time()-t0)*1000)/1000 / 60:.1f}分钟")

conn.close()
