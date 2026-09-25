import sys
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
from core.db import get_state_db
con = get_state_db()
cols = con.execute("PRAGMA table_info('sig.fusion_3f_signals')").fetchall()
print('fusion cols:', [c[1] for c in cols])
d = con.execute("SELECT MAX(date) FROM sig.fusion_3f_signals").fetchone()[0]
print('max date', d)
codes = ['688636', '301557', '603202', '002454', '605598', '688093', '300658', '688186',
         '300986', '301110', '301093', '001332', '603966', '301237', '601615']
for c in codes:
    r = con.execute("SELECT * FROM sig.fusion_3f_signals WHERE REPLACE(REPLACE(stock_code,'.SH',''),'.SZ','')=? ORDER BY date DESC LIMIT 1", [c]).fetchall()
    print(c, r)
con.close()
