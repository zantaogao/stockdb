import sqlite3, sys
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
from core.db import get_state_db

con = get_state_db()
codes = ['688636', '301557', '603202', '002454', '605598', '688093', '300658', '688186',
         '300986', '301110', '301093', '001332', '603966', '301237', '601615']
print('=== 持仓在最新信号日的评分 ===')
try:
    d = con.execute("SELECT MAX(date) FROM sig.fusion_3f_signals").fetchone()[0]
    print('fusion 最新日期:', d)
except Exception as e:
    print('err', e)
    d = None
for c in codes:
    row = None
    for q in ["SELECT date, score FROM sig.fusion_3f_signals WHERE REPLACE(stock_code,'.SH','')||'' LIKE ? ORDER BY date DESC LIMIT 1"]:
        pass
    try:
        r = con.execute("SELECT date, stock_code, score FROM sig.fusion_3f_signals WHERE REPLACE(REPLACE(stock_code,'.SH',''),'.SZ','')=? ORDER BY date DESC LIMIT 3", [c]).fetchall()
        print(c, r)
    except Exception as e:
        print(c, 'err', e)
print('\n=== 主账户 watchlist ===')
try:
    for r in con.execute("SELECT * FROM watchlist ORDER BY rowid DESC LIMIT 15").fetchall():
        print(r)
except Exception as e:
    print('err', e)
con.close()
