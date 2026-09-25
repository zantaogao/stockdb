#!/usr/bin/env python3
"""终极复现: 从 bak.local(08-07=0, 缺口场景) 跑 update_stk_factor, 看是否写双份 2026-08-08"""
import os, sys, subprocess, shutil

sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')

SRC = '/Users/zantao/.hermes/stockdb/tushare.db.bak.local'  # 08-07=0 的缺口库
TEST = '/tmp/test_gapfix.db'

if os.path.exists(TEST):
    os.unlink(TEST)
r = subprocess.run(['cp', '-c', SRC, TEST], capture_output=True)
if r.returncode != 0:
    shutil.copy2(SRC, TEST)

import duckdb
c = duckdb.connect(TEST, read_only=True)
n0 = c.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260807'").fetchone()[0]
mx = c.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0]
tot0 = c.execute("SELECT COUNT(*) FROM stk_factor").fetchone()[0]
c.close()
print(f"测试库(缺口场景): 08-07={n0} 行, MAX={mx}, 总行={tot0}")

# 模拟 main() 的 set_active_db(TEMP_DB)——指向测试库（缺口的"活库"）
import update_tushare_api as ut
ut._ACTIVE_DB = __import__('pathlib').Path(TEST)

pro = ut.get_pro()
n = ut.update_stk_factor(pro)
print(f"update_stk_factor 返回: {n}")

c = duckdb.connect(TEST, read_only=True)
n1 = c.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260807'").fetchone()[0]
tot1 = c.execute("SELECT COUNT(*) FROM stk_factor").fetchone()[0]
# 重复代码检查
dup = c.execute("SELECT COUNT(*) FROM (SELECT ts_code FROM stk_factor WHERE trade_date='20260807' GROUP BY ts_code HAVING COUNT(*)>1)").fetchone()[0]
c.close()
print(f"测试库 08-07: 前={n0} 后={n1}, 重复代码={dup}, 总行 {tot0}->{tot1}")
print("结论:", "✅ 幂等单份" if dup == 0 and n1 <= 5535 else "❌ 缺口恢复写双份")

os.unlink(TEST)
