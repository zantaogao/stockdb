"""校验 tushare.db.new 完整性（全表强读触发 checksum）+ 各关键表最新日"""
import duckdb
from pathlib import Path

DB = Path('/Users/zantao/.hermes/stockdb/tushare.db.new')
print(f'校验 {DB} ({DB.stat().st_size/1e9:.1f}GB)')
conn = duckdb.connect(str(DB), read_only=True)

tables = conn.execute(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY table_name").fetchall()
total = 0
for (t,) in tables:
    cur = conn.cursor()
    cur.execute(f'SELECT * FROM "{t}"')
    cnt = 0
    while True:
        batch = cur.fetchmany(50000)
        if not batch:
            break
        cnt += len(batch)
    cur.close()
    total += cnt
    print(f'  {t}: {cnt:,} 行')

print(f'\n✅ 全表强读通过: {len(tables)} 表, {total:,} 行')

# 关键表最新交易日
for t, col in [('daily', 'trade_date'), ('daily_basic', 'trade_date'),
               ('stk_factor', 'trade_date'), ('stk_factor_pro', 'trade_date'),
               ('fund_daily', 'trade_date'), ('index_daily_raw', 'trade_date'),
               ('moneyflow', 'trade_date'), ('stk_limit', 'trade_date')]:
    try:
        r = conn.execute(f'SELECT MAX({col}) FROM {t}').fetchone()[0]
        print(f'  {t} 最新: {r}')
    except Exception as e:
        print(f'  {t}: {e}')
conn.close()
