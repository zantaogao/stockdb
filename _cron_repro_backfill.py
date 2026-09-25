#!/usr/bin/env python3
"""复现 backfill 场景: _ACTIVE_DB=活库(测试副本) + update_stk_factor 2026-08-08
目标: 确认 10:00 backfill 是否会把 08-07 写成双份"""
import os, sys, shutil

sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')

SRC = '/Users/zantao/.hermes/stockdb/tushare.db'
TEST = '/tmp/test_tushare_backfill.db'

# 1. 克隆测试库（APFS CoW 秒级）
if os.path.exists(TEST):
    os.unlink(TEST)
import subprocess
r = subprocess.run(['cp', '-c', SRC, TEST], capture_output=True)
if r.returncode != 0:
    # 回退普通拷贝
    shutil.copy2(SRC, TEST)
import duckdb
c = duckdb.connect(TEST, read_only=True)
n_before = c.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260807'").fetchone()[0]
mx = c.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0]
c.close()
print(f"测试库克隆完成: 08-07={n_before} 行, MAX={mx}")

# 2. 模拟 backfill: _ACTIVE_DB 指向测试库
import update_tushare_api as ut
ut._ACTIVE_DB = __import__('pathlib').Path(TEST)
# 确保 TEMP_DB 不指向测试库（backfill 不跑 main, 无克隆）
print(f"_ACTIVE_DB = {ut._ACTIVE_DB}")

# 3. 调 update_stk_factor（真实 API）
pro = ut.get_pro()
n = ut.update_stk_factor(pro)
print(f"update_stk_factor 返回: {n}")

# 4. 检查测试库 08-07 行数
c = duckdb.connect(TEST, read_only=True)
n_after = c.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260807'").fetchone()[0]
print(f"测试库 08-07 行数: 前={n_before} 后={n_after}")
print("结论:", "✅ 未翻倍(backfill 无辜)" if n_after == n_before else "❌ 翻倍(backfill 是凶手)")
c.close()

# 清理
os.unlink(TEST)
print("测试库已清理")
