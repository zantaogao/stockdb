#!/usr/bin/env python3
"""清理 stk_factor 08-07 重复行（保留每 ts_code 一行），走原子交换 2026-08-08
08-07 双份根因: 8/7 23:06 遗留进程与 02:22 update_data.sh 并发踩踏共享 TEMP_DB 路径。
"""
import os, sys, shutil, subprocess

sys.path.insert(0, '/Users/zantao/.hermes/stockdb')

BASE = '/Users/zantao/.hermes/stockdb'
TUSHARE = os.path.join(BASE, 'tushare.db')
TEMP = os.path.join(BASE, 'tushare.db.new')

from core.db_lock import tushare_write_lock
import duckdb

with tushare_write_lock(timeout=600):
    # 1. 备份当前活库（双份状态，可回滚）
    bak = TUSHARE + '.bak.20260808_dup'
    if not os.path.exists(bak):
        subprocess.run(['cp', '-c', TUSHARE, bak], check=True)
        print(f"✅ 备份: {bak}")

    # 2. 克隆到临时库
    if os.path.exists(TEMP):
        os.unlink(TEMP)
    subprocess.run(['cp', '-c', TUSHARE, TEMP], check=True)
    print("✅ 克隆到临时库")

    # 3. 去重 08-07
    con = duckdb.connect(TEMP)
    before = con.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260807'").fetchone()[0]
    dup = con.execute("""
        SELECT COUNT(*) FROM (SELECT ts_code FROM stk_factor WHERE trade_date='20260807' GROUP BY ts_code HAVING COUNT(*)>1)
    """).fetchone()[0]
    con.execute("""
        CREATE TEMP TABLE _dedup AS
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY 1) rn
            FROM stk_factor WHERE trade_date='20260807'
        ) WHERE rn = 1
    """)
    con.execute("DELETE FROM stk_factor WHERE trade_date='20260807'")
    con.execute("INSERT INTO stk_factor SELECT * EXCLUDE (rn) FROM _dedup")
    con.execute("CHECKPOINT")
    after = con.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260807'").fetchone()[0]
    con.close()
    print(f"✅ 08-07 去重: {before} -> {after} 行 (重复代码 {dup} 只)")

    # 4. 校验临时库
    vc = duckdb.connect(TEMP, read_only=True)
    n = vc.execute("SELECT COUNT(*) FROM stk_factor").fetchone()[0]
    tot = vc.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260807'").fetchone()[0]
    vc.close()
    print(f"✅ 临时库校验: stk_factor 总 {n} 行, 08-07 {tot} 行")

    # 5. 原子交换
    os.replace(TEMP, TUSHARE)
    print("✅ 原子交换完成")

    # 6. 复验
    vc = duckdb.connect(TUSHARE, read_only=True)
    n = vc.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260807'").fetchone()[0]
    dup2 = vc.execute("SELECT COUNT(*) FROM (SELECT ts_code FROM stk_factor WHERE trade_date='20260807' GROUP BY ts_code HAVING COUNT(*)>1)").fetchone()[0]
    vc.close()
    print(f"✅ 活库复验: 08-07={n} 行, 重复代码={dup2}")
