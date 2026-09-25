import duckdb, datetime, sqlite3
from pathlib import Path
OUT = Path('/Users/zantao/.hermes/stockdb/schema')
# tushare 真名表清单
con=duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
want={'stock_daily','adj_factor','trade_cal','stock_basic','repurchase','forecast','fund_daily','fund_basic'}
names=sorted({r[0] for r in con.execute("select table_name from information_schema.tables").fetchall() if r[0] in want or any(r[0].startswith(w) for w in ('stock_daily','adj_factor'))})
print('tushare 命中表:', names)
lines=[f'-- tushare.db 关键表 DDL {datetime.date.today()} 基线（DuckDB；stock_daily 若系 VIEW 见 duckdb_views）']
for t in names:
    d=con.execute("select sql from duckdb_tables() where table_name=?",(t,)).fetchone()
    if not d or not d[0]:
        d=con.execute("select sql from duckdb_views() where view_name=?",(t,)).fetchone()
    lines.append((d[0] if d and d[0] else f'-- [缺] {t}')+';')
(OUT/'tushare_tables.sql').write_text('\n'.join(lines)+'\n')
print('tushare_tables.sql', len(names),'表')
con.close()
# factors: SQLite 头？
hdr=open('/Users/zantao/.hermes/stockdb/factors.db','rb').read(6); print('factors header:',hdr)

lines=[f'-- factors.db DDL {datetime.date.today()} 基线']
if hdr==b'SQLite':
    fc=sqlite3.connect('file:/Users/zantao/.hermes/stockdb/factors.db?mode=ro', uri=True)
    for t,s in fc.execute("select name,sql from sqlite_master where type in ('table','view') order by name"):
        lines.append((s or f'-- [无SQL] {t}')+';')
    (OUT/'factors.sql').write_text('\n'.join(lines)+'\n')
    print('factors.sql', len(lines)-1, '表/视图(SQLite)')
