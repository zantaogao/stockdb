#!/usr/bin/env python3
"""TDX 分钟原始数据归档（2026-08-08 用户要求: 突破通达信半年窗口限制）
输入: PC 导出的 min1/min5 CSV（与 tdx_import_csv.py 同源）
输出: tdx_archive.db (DuckDB) 表 min1_archive / min5_archive
      按 (date, code, tm) 主键幂等——重复跑不产生重复行
用法: python3 -B scripts/tdx_archive.py [min1.csv] [min5.csv]
"""
import duckdb, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ARCHIVE_DB = BASE / 'tdx_archive.db'
TABLE_MAP = {'min1': 'min1_archive', 'min5': 'min5_archive'}

def archive_csv(fn, tbl):
    import pandas as pd
    if not Path(fn).exists() or Path(fn).stat().st_size == 0:
        print(f'  ⏭ {fn} 不存在或为空')
        return 0
    df = pd.read_csv(fn, dtype={'code': str})
    if df.empty:
        print(f'  ⏭ {fn} 无数据行')
        return 0
    df['date'] = df['datetime'].str[:8].astype(int)
    df['tm'] = df['datetime'].str[9:11].astype(int) * 60 + df['datetime'].str[11:13].astype(int)
    df = df[['date', 'code', 'market', 'tm', 'open', 'high', 'low', 'close', 'volume']]
    # 0929修复: 上游pytdx偶发同主键重复行(实锤: 301273.SZ 20260923 224行重复)→INSERT主键冲突整批崩溃。
    # 归档前按主键去重(留首行)，重复>0时打告警行供 tdx_sync.sh/巡逻可见。
    n_dup = df.duplicated(subset=['date', 'code', 'market', 'tm']).sum()
    if n_dup:
        print(f'  ⚠️ {fn} 上游重复主键 {n_dup} 行, 去重后入库')
        df = df.drop_duplicates(subset=['date', 'code', 'market', 'tm'], keep='first')
    db = duckdb.connect(str(ARCHIVE_DB))
    try:
        db.execute(f"""CREATE TABLE IF NOT EXISTS {tbl} (
            date INTEGER, code VARCHAR, market VARCHAR, tm INTEGER,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
            PRIMARY KEY (date, code, market, tm))""")
        for d in df['date'].unique():
            db.execute(f"DELETE FROM {tbl} WHERE date=?", (int(d),))
        db.execute(f"INSERT INTO {tbl} SELECT date, code, market, tm, open, high, low, close, volume FROM df")
        n = db.execute(f"SELECT COUNT(*) FROM {tbl} WHERE date IN (SELECT DISTINCT date FROM df)").fetchone()[0]
        print(f'  ✅ {fn} → {tbl}: {len(df)} 行归档 (该日期段共 {n} 行)')
        return len(df)
    finally:
        db.close()

if __name__ == '__main__':
    c1 = sys.argv[1] if len(sys.argv) > 1 else '/tmp/tdx_min1_recent.csv'
    c5 = sys.argv[2] if len(sys.argv) > 2 else '/tmp/tdx_min5_recent.csv'
    n1 = archive_csv(c1, TABLE_MAP['min1'])
    n5 = archive_csv(c5, TABLE_MAP['min5'])
    db = duckdb.connect(str(ARCHIVE_DB))
    for tbl in TABLE_MAP.values():
        try:
            r = db.execute(f"SELECT COUNT(*), COUNT(DISTINCT date), MIN(date), MAX(date) FROM {tbl}").fetchone()
            print(f'{tbl}: {r[0]} 行, {r[1]} 个交易日, {r[2]} ~ {r[3]}')
        except Exception as e:
            print(f'{tbl}: {e}')
    db.close()
