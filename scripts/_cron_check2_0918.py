import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
# cmmr 300935 / cmmr_fusion 688793 positions
for a, code in [('cmmr','300935'),('cmmr_fusion','688793')]:
    rows = c.execute("SELECT * FROM strategy_positions WHERE account_id=? AND code LIKE ?", (a, code+'%')).fetchall()
    print(a, code, rows)
# any sells today across strategies
print('sells today:', c.execute("SELECT code,direction,strategy FROM trade_log WHERE trade_date LIKE '2026-09-18%' AND direction='SELL'").fetchall())
print('agent_auto cash:', c.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id='agent_auto'").fetchone())
