# 回放第一步：盘点 8 月以来策略账户交易事件与可用上下文
import sqlite3

c = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
for t in ('execution_logs', 'trade_signals', 'trade_cooldown'):
    cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
    n = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'== {t} (n={n}) cols: {cols}')
    for r in c.execute(f'SELECT * FROM {t} LIMIT 3'):
        print('   ', r)
print()
for r in c.execute("SELECT strategy, COUNT(*), MIN(trade_date), MAX(trade_date) FROM trade_log GROUP BY strategy"):
    print('  strategy=%s n=%s %s~%s' % r)