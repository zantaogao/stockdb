#!/usr/bin/env python3
"""原子交换：重建临时库 → 活库（带全表强读校验 + 回滚）"""
import os, sys, shutil, time, warnings
import duckdb
from pathlib import Path
from datetime import datetime

warnings.filterwarnings('ignore')
BASE = Path.home() / '.hermes' / 'stockdb'
TMP = BASE / 'tushare.db.rebuild_tmp'
LIVE = BASE / 'tushare.db'
BAK = BASE / 'tushare.db.bak.pre_fin_rebuild'

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def verify_db(path):
    """全表强读校验（触发所有 block checksum）"""
    conn = duckdb.connect(str(path), read_only=True)
    tables = conn.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY 1
    """).fetchall()
    total_rows = 0
    for (t,) in tables:
        n = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        total_rows += n
    conn.close()
    return len(tables), total_rows

# 1. 校验临时库
log("=== 1. 校验临时库（全表强读）===")
t0 = time.time()
n_tables, n_rows = verify_db(TMP)
log(f"  临时库: {n_tables} 表, {n_rows:,} 行, 耗时 {time.time()-t0:.0f}s")

# 2. 校验活库（对照）
log("=== 2. 校验活库（对照）===")
t0 = time.time()
n_tables_l, n_rows_l = verify_db(LIVE)
log(f"  活库: {n_tables_l} 表, {n_rows_l:,} 行, 耗时 {time.time()-t0:.0f}s")

# 3. 备份活库
log("=== 3. 备份活库 ===")
if not BAK.exists():
    log(f"  克隆活库 → {BAK.name} (CoW)")
    if hasattr(os, 'clonefile'):
        os.clonefile(str(LIVE), str(BAK))
    else:
        shutil.copy2(str(LIVE), str(BAK))
else:
    log(f"  ⚠️ 备份已存在，跳过: {BAK.name}")

# 4. 原子替换
log("=== 4. 原子替换 ===")
os.replace(str(TMP), str(LIVE))
log("  ✅ 已替换")

# 5. 复验活库
log("=== 5. 复验活库 ===")
t0 = time.time()
try:
    n_tables_v, n_rows_v = verify_db(LIVE)
    log(f"  活库复验: {n_tables_v} 表, {n_rows_v:,} 行, 耗时 {time.time()-t0:.0f}s")
    if n_tables_v != n_tables:
        raise Exception(f"表数不符: {n_tables_v} vs {n_tables}")
    log("  ✅ 复验通过")
except Exception as e:
    log(f"  ❌ 复验失败: {e}")
    log("  ⚠️ 回滚...")
    os.replace(str(BAK), str(LIVE))
    log("  ✅ 已回滚到备份")
    sys.exit(1)

# 6. 清理 legacy 表（重建的旧数据已不需要——保留在备份库中）
log("=== 6. 清理 legacy 表 ===")
conn = duckdb.connect(str(LIVE))
for t in ['fin_income_legacy', 'fin_balancesheet_legacy', 'fin_cashflow_legacy']:
    try:
        conn.execute(f"DROP TABLE IF EXISTS {t}")
        log(f"  ✅ DROP {t}")
    except Exception as e:
        log(f"  ⚠️ {t}: {str(e)[:50]}")
conn.execute("CHECKPOINT")
conn.close()
log("\n🎉 全部完成！")
