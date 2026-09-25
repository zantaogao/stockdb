import sqlite3
base = '/Users/zantao/.hermes/stockdb'
c = sqlite3.connect(base + '/ledger.db')
print(c.execute("SELECT sql FROM sqlite_master WHERE name='strategy_positions'").fetchone()[0])
print(c.execute("SELECT sql FROM sqlite_master WHERE name='strategy_accounts_meta'").fetchone()[0])
codes = ['600198','600395','600403','601001','601991','000545','001260','002565','002972','300036','300444','300511','300772','601615','603279','603585','603665']
q = "SELECT * FROM strategy_positions WHERE account IN ('fusion3f','fusion_dual')"
print(c.execute(q).fetchall())
for t in ('strategy_accounts_meta','strategy_accounts_legacy'):
    try:
        print(t, c.execute(f"SELECT * FROM {t} LIMIT 10").fetchall())
    except Exception as e:
        print(t, 'ERR', e)
