import sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(f'{BASE}/ledger.db', timeout=10)
c.execute("PRAGMA busy_timeout=5000")
c.execute("ATTACH DATABASE ? AS sig", (f'{BASE}/signals.db',))
try:
    r = c.execute("SELECT industry FROM sig.stock_basic WHERE stock_code='300986'").fetchone()
    print('sig.stock_basic query:', r)
except Exception as e:
    print('sig.stock_basic query ERR:', e)
c.close()
# any BUY trades since v2 migration 08-29?
c = sqlite3.connect(f'file:{BASE}/ledger.db?mode=ro', uri=True)
print('trades since 08-28:', c.execute("select trade_date,direction,code from trade_log where trade_date>='2026-08-28' order by trade_date").fetchall())
c.close()
# correct source check
import duckdb
d = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
print('tushare stock_basic 300986:', d.execute("select industry from stock_basic where ts_code='300986.SZ'").fetchone())
d.close()