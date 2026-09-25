import sqlite3

c = sqlite3.connect('/Users/zantao/.hermes/cron/executions.db')
rows = c.execute("SELECT status, started_at, finished_at, error FROM executions WHERE job_id='099aee371ab5' ORDER BY rowid DESC LIMIT 4").fetchall()
for r in rows:
    print(r)

# Confirm signal chain state for today (2026-09-01) across both DBs
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('new_factors latest:', sig.execute("SELECT trade_date, COUNT(*) FROM new_factors GROUP BY 1 ORDER BY 1 DESC LIMIT 1").fetchone())
print('fusion_3f latest:', sig.execute("SELECT signal_date, COUNT(*) FROM fusion_3f_signals GROUP BY 1 ORDER BY 1 DESC LIMIT 1").fetchone())
print('fusion_center latest:', sig.execute("SELECT trade_date, COUNT(*) FROM fusion_center_signals GROUP BY 1 ORDER BY 1 DESC LIMIT 1").fetchone())