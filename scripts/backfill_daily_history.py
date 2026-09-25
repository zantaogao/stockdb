#!/usr/bin/env python3
"""老股 2005 前 daily 历史补拉 v2 (2026-08-26)
v1 失败根因: pro.daily(ts_code) 不传参数单次最多返回 6000 行 → 27年老股历史被截断
            (600000 浦发 1999 上市只拿到 2001 起; 农行 2010 上市 <6000 行全量→100%吻合)。
v2 修复: 带 start_date='19900101' end_date='20050104' 分批拉 2005 前全量;
        只处理 MIN(trade_date) > list_date 的老股(被截断未补全的);
        校验/交换用独立连接, 用完即关(修复 v1 写连接未关导致只读连接冲突)。
"""
import os, sys, time, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core.db_lock import tushare_write_lock
import update_tushare_api as ut
import duckdb

START = '19900101'
CUTOFF = '20050104'
SLEEP = 0.3

with tushare_write_lock(timeout=600):
    print("=" * 60)
    print("老股 2005 前 daily 历史补拉 v2（带 start_date, 修截断）")
    print("=" * 60)

    # 0. 清单: 老股中 daily MIN(trade_date) > list_date 的(未补全)
    rc = duckdb.connect(str(ut.TUSHARE_DB), read_only=True)
    rows = rc.execute("""
        SELECT b.ts_code, b.list_date,
               (SELECT MIN(trade_date) FROM daily d WHERE d.ts_code=b.ts_code) as dmin
        FROM stock_basic b
        WHERE b.list_date IS NOT NULL AND b.list_date < '20050104'
          AND b.ts_code IN (SELECT DISTINCT ts_code FROM daily)
    """).fetchall()
    rc.close()
    todo = [(t, str(l).replace('-', ''), str(m).replace('-', '')) for t, l, m in rows
            if m is None or m > str(l).replace('-', '')]
    print(f"需补全老股: {len(todo)} 只 (共 {len(rows)} 只老股)")

    # 1. 清理 + CHECKPOINT + 克隆
    if ut.TEMP_DB.exists():
        ut.TEMP_DB.unlink()
    _tmp_wal = Path(str(ut.TEMP_DB) + '.wal')
    if _tmp_wal.exists():
        _tmp_wal.unlink()
    try:
        vc = duckdb.connect(str(ut.TUSHARE_DB), read_only=False)
        vc.execute("CHECKPOINT")
        vc.close()
        print("✅ 活库 CHECKPOINT 完成")
    except Exception as e:
        print(f"⚠️ CHECKPOINT 失败: {str(e)[:100]}")
    r = subprocess.run(['cp', '-c', str(ut.TUSHARE_DB), str(ut.TEMP_DB)], capture_output=True)
    if r.returncode != 0:
        import shutil
        shutil.copy2(str(ut.TUSHARE_DB), str(ut.TEMP_DB))
    print("✅ 克隆到临时库")

    # 2. 切换写入目标 + 连接(保持打开用于 upsert, 校验阶段先关再开只读)
    ut.set_active_db(ut.TEMP_DB)
    db = ut.get_db_writable()
    pro = ut.get_pro()

    # 3. 逐股补拉 2005 前全量
    total_rows = 0
    n_ok = n_fail = n_skip = 0
    for i, (code, list_date, dmin) in enumerate(todo):
        try:
            df = pro.daily(ts_code=code, start_date=START, end_date=CUTOFF)
        except Exception as e:
            print(f"⚠️ [{i+1}/{len(todo)}] {code} 拉取失败: {str(e)[:80]}")
            n_fail += 1
            time.sleep(1.0)
            continue
        if df is None or len(df) == 0:
            n_skip += 1
            time.sleep(SLEEP)
            continue
        df = df[df['trade_date'] < CUTOFF]
        if len(df) == 0:
            n_skip += 1
            time.sleep(SLEEP)
            continue
        n = ut.upsert_df(db, df, 'daily', where_col='ts_code', where_val=code)
        if n > 0:
            total_rows += n
            n_ok += 1
        else:
            n_fail += 1
        if (i + 1) % 50 == 0:
            print(f"  进度 {i+1}/{len(todo)}: 已补 {n_ok} 只, +{total_rows} 行, 失败 {n_fail}")
        time.sleep(SLEEP)

    print(f"\n补拉完成: 成功 {n_ok} 只, +{total_rows} 行, 跳过 {n_skip}, 失败 {n_fail}")
    db.close()  # 关写连接, 释放 TEMP_DB

    # 4. 校验 (独立只读连接)
    vc = duckdb.connect(str(ut.TEMP_DB), read_only=True)
    new_min = vc.execute("SELECT MIN(trade_date) FROM daily").fetchone()[0]
    new_max = vc.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    new_cnt = vc.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    # 抽查补全情况: list_date 与 daily MIN 差距
    spot = vc.execute("""
        SELECT b.ts_code, b.list_date, MIN(d.trade_date)
        FROM stock_basic b JOIN daily d ON b.ts_code=d.ts_code
        WHERE b.ts_code IN ('000001.SZ','600000.SH','000828.SZ','601288.SH')
        GROUP BY b.ts_code, b.list_date
    """).fetchall()
    vc.close()
    print(f"TEMP_DB daily: MIN={new_min} MAX={new_max} 总行数={new_cnt}")
    for s in spot:
        print(f"  抽查 {s[0]}: list_date={s[1]} daily MIN={s[2]}")
    if str(new_min).replace('-', '') >= CUTOFF:
        print("❌ 校验失败: MIN 未提前, 中止交换")
        sys.exit(1)

    # 5. CHECKPOINT + 交换
    vc = duckdb.connect(str(ut.TEMP_DB), read_only=False)
    vc.execute("CHECKPOINT")
    vc.close()
    os.replace(str(ut.TEMP_DB), str(ut.TUSHARE_DB))
    ut.set_active_db(ut.TUSHARE_DB)
    print("✅ 原子交换完成")

    # 6. 活库复验
    vc = duckdb.connect(str(ut.TUSHARE_DB), read_only=True)
    vmin = vc.execute("SELECT MIN(trade_date) FROM daily").fetchone()[0]
    vcnt = vc.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    vc.close()
    print(f"活库复验: MIN={vmin} 总行数={vcnt}")
    print("✅ v2 补拉完成")
