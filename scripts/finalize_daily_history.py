#!/usr/bin/env python3
"""补历史收尾: 校验 TEMP_DB(已含补拉数据) → 备份活库 → 原子交换
原 backfill_daily_history.py 在拉取完成后校验阶段因写连接未关导致
'Can't open a connection to same database file with a different configuration' 失败。
本脚本只做收尾(数据已在 TEMP_DB), 所有连接用完即关, 避免配置冲突。
"""
import os, sys, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core.db_lock import tushare_write_lock
import update_tushare_api as ut
import duckdb

CUTOFF = '20050104'

with tushare_write_lock(timeout=600):
    print("=" * 60)
    print("补历史收尾: 校验+备份+原子交换")
    print("=" * 60)

    if not ut.TEMP_DB.exists():
        print("❌ TEMP_DB 不存在, 无数据可交换")
        sys.exit(1)

    # 1. 校验 TEMP_DB (只读连接, 用完即关)
    vc = duckdb.connect(str(ut.TEMP_DB), read_only=True)
    new_min = vc.execute("SELECT MIN(trade_date) FROM daily").fetchone()[0]
    new_max = vc.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    new_cnt = vc.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    old_cnt = vc.execute("SELECT COUNT(*) FROM daily WHERE trade_date >= '20050104'").fetchone()[0]
    vc.close()
    print(f"TEMP_DB daily: MIN={new_min} MAX={new_max} 总行数={new_cnt} (2005后={old_cnt})")
    if str(new_min).replace('-', '') >= CUTOFF:
        print("❌ 校验失败: MIN 未提前到 2005 前, 中止交换")
        sys.exit(1)

    # 2. 备份活库 (cp -c CoW, 不占双份空间)
    bak_local = str(ut.TUSHARE_DB) + '.bak.local'
    try:
        if os.path.exists(bak_local):
            os.unlink(bak_local)
        r = subprocess.run(['cp', '-c', str(ut.TUSHARE_DB), bak_local], capture_output=True, timeout=120)
        if r.returncode == 0:
            print(f"✅ 活库已备份到 {bak_local} (CoW)")
        else:
            import shutil
            shutil.copy2(str(ut.TUSHARE_DB), bak_local)
            print(f"✅ 活库已备份到 {bak_local} (copy2)")
    except Exception as e:
        print(f"⚠️ 备份失败(继续): {str(e)[:100]}")

    # 3. CHECKPOINT (可写连接, 用完即关)
    vc = duckdb.connect(str(ut.TEMP_DB), read_only=False)
    vc.execute("CHECKPOINT")
    vc.close()
    print("✅ TEMP_DB CHECKPOINT 完成")

    # 4. 原子交换
    os.replace(str(ut.TEMP_DB), str(ut.TUSHARE_DB))
    ut.set_active_db(ut.TUSHARE_DB)
    print("✅ 原子交换完成")

    # 5. 活库复验
    vc = duckdb.connect(str(ut.TUSHARE_DB), read_only=True)
    vmin = vc.execute("SELECT MIN(trade_date) FROM daily").fetchone()[0]
    vmax = vc.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    vcnt = vc.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    spot = vc.execute("""
        SELECT ts_code, MIN(trade_date), COUNT(*) FROM daily
        WHERE ts_code IN ('000001.SZ','000828.SZ','600000.SH','601288.SH') GROUP BY ts_code
    """).fetchall()
    vc.close()
    print(f"活库复验: MIN={vmin} MAX={vmax} 总行数={vcnt}")
    for s in spot:
        print(f"  抽查 {s[0]}: MIN={s[1]} 行数={s[2]}")
    print("✅ 全部完成")
