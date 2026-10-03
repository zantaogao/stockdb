# verify cash figure 995 is real: read account_balance + holdings from ledger.db
import duckdb, os
con = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'), read_only=True)
cols = [d[0] for d in con.sql("SELECT * FROM account_balance LIMIT 0").description]
print('account_balance cols:', cols)
for r in con.sql("SELECT * FROM account_balance ORDER BY rowid DESC LIMIT 3").fetchall():
    print(r)
print('holdings:', con.sql("SELECT COUNT(*), COALESCE(SUM(market_value),0) FROM holdings").fetchall())
con.close()
