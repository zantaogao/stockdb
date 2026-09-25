import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=15)
for tid in ['main','agent_auto','center_dual','fusion_center','cmmr','cmmr_fusion','reg10_solo','cmmr_clf','fusion_dual','fusion3f']:
    print(tid, c.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id=?", (tid,)).fetchall())
print(c.execute("SELECT SUM(CASE WHEN direction='BUY' THEN amount ELSE 0 END), COUNT(*) FROM trade_log WHERE trade_date='2026-09-24' AND strategy='agent_auto'").fetchall())
