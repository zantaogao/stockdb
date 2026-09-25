#!/usr/bin/env python3
"""历史基线归档: 本地 tdx/vipdoc 全部 lc1/lc5 → tdx_archive.db（2026-08-08 一次性）
把通达信客户端现有的 116 天分钟数据全量归档, 作为长期样本基线
用法: python3 -B scripts/tdx_archive_historical.py
"""
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / 'scripts'))

import importlib.util
spec = importlib.util.spec_from_file_location('tdxagg', str(BASE / 'scripts' / 'tdx_intraday_agg.py'))
tdxagg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tdxagg)
import glob, duckdb, csv, io

TDX = BASE / 'tdx' / 'vipdoc'
ARCHIVE_DB = BASE / 'tdx_archive.db'

def archive_lc1_files(glob_pattern, tbl, is_min1=True):
    files = sorted(glob.glob(glob_pattern))
    db = duckdb.connect(str(ARCHIVE_DB))
    # 主键含 market（sh000001 指数 与 sz000001 平安银行 code 相同, 2026-08-08 修复）
    db.execute(f"""CREATE TABLE IF NOT EXISTS {tbl} (
        date INTEGER, code VARCHAR, market VARCHAR, tm INTEGER,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
        PRIMARY KEY (date, code, market, tm))""")
    total = 0
    for i, fn in enumerate(files):
        name = Path(fn).name
        market = name[:2]
        code = name[2:8]
        df = tdxagg.parse_lc1(fn)  # 列: date, t, open, high, low, close, vol, tm
        if df.empty:
            continue
        sub = df[['date', 'tm', 'open', 'high', 'low', 'close', 'vol']].copy()
        sub['code'] = code
        sub['market'] = market
        sub = sub.rename(columns={'vol': 'volume'})
        sub = sub[['date', 'code', 'market', 'tm', 'open', 'high', 'low', 'close', 'volume']]
        db.execute(f"INSERT OR REPLACE INTO {tbl} SELECT date, code, market, tm, open, high, low, close, volume FROM sub")
        total += len(sub)
        if (i + 1) % 1000 == 0:
            print(f'  {tbl}: 已处理 {i+1}/{len(files)}')
    n = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    nd = db.execute(f"SELECT COUNT(DISTINCT date) FROM {tbl}").fetchone()[0]
    print(f'  ✅ {tbl}: {n} 行, {nd} 个交易日')
    db.close()

print('归档 1 分钟历史...')
archive_lc1_files(str(TDX / 'sh' / 'minline' / '*.lc1'), 'min1_archive')
archive_lc1_files(str(TDX / 'sz' / 'minline' / '*.lc1'), 'min1_archive')
print('归档 5 分钟历史...')
archive_lc1_files(str(TDX / 'sh' / 'fzline' / '*.lc5'), 'min5_archive')
archive_lc1_files(str(TDX / 'sz' / 'fzline' / '*.lc5'), 'min5_archive')
print('历史基线归档完成')
