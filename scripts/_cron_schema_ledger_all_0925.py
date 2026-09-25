import sqlite3, datetime
from pathlib import Path
OUT = Path('/Users/zantao/.hermes/stockdb/schema')
con=sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
lines=[f'-- ledger.db 全表 DDL {datetime.date.today()} 基线']
for t,s in con.execute("select name,sql from sqlite_master where type='table' order by name"):
    lines.append((s or f'-- [无SQL] {t}')+';')
(OUT/'ledger.sql').write_text('\n'.join(lines)+'\n')
print('ledger.sql', len(lines)-1, '表(全)')
