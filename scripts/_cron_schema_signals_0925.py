import sqlite3, duckdb, datetime
from pathlib import Path
OUT = Path('/Users/zantao/.hermes/stockdb/schema')
db='/Users/zantao/.hermes/stockdb/signals.db'
hdr=open(db,'rb').read(6)
print('header:', hdr)
lines=[f'-- signals.db DDL {datetime.date.today()} 基线']
if hdr==b'SQLite':
    con=sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    for t,s in con.execute("select name,sql from sqlite_master where type='table' order by name"):
        lines.append((s or f'-- [虚拟/无SQL] {t}')+';')
else:
    con=duckdb.connect(db, read_only=True)
    ts=[r[0] for r in con.execute("select table_name from information_schema.tables order by 1")]
    for t in ts:
        d=con.execute("select sql from duckdb_tables() where table_name=?",(t,)).fetchone()
        lines.append((d[0] if d and d[0] else f'-- [缺] {t}')+';')
(OUT/'signals.sql').write_text('\n'.join(lines)+'\n')
print('signals.sql', len(lines)-1, '表')
