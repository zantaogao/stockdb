# tushare.db/信号等 DuckDB 关键表 DDL（Task 1.2）
import duckdb, datetime
from pathlib import Path
OUT = Path('/Users/zantao/.hermes/stockdb/schema')
specs = [
  ('/Users/zantao/.hermes/stockdb/tushare.db', ['stock_daily','fund_daily','fund_basic','adj_factor','trade_cal','stock_basic','repurchase','forecast'], 'tushare_tables.sql'),
  ('/Users/zantao/.hermes/stockdb/signals.db', None, 'signals.sql'),
  ('/Users/zantao/.hermes/stockdb/factors.db', ['shadow_fusion_442_daily','shadow_fusion_442'], 'factors.sql'),
]
for db, tables, name in specs:
    try:
        con = duckdb.connect(db, read_only=True)
        if tables is None:
            tables = [r[0] for r in con.execute("select table_name from information_schema.tables order by 1")]
        lines=[f'-- {db} DDL {datetime.date.today()} 基线']
        for t in tables:
            try:
                d = con.execute(f"select sql from duckdb_tables() where table_name=?", (t,)).fetchone()
                lines.append((d[0] if d and d[0] else f'-- [缺] {t}') + ';')
            except Exception as e:
                lines.append(f'-- [err] {t}: {e}')
        (OUT/name).write_text('\n'.join(lines)+'\n')
        print(name, len(lines)-1, '表')
        con.close()
    except Exception as e:
        print('[SKIP]', name, str(e)[:80])
