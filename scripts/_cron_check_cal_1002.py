import duckdb, os
db = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = duckdb.connect(db, read_only=True)
rows = con.execute("""
    select cal_date, is_open from trade_cal
    where cal_date between '20260928' and '20261010' order by cal_date
""").fetchall()
for r in rows:
    print(r)
