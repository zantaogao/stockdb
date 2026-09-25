"""核查: strategy_accounts(视图/表)最新行 + 今日 NAV 残差; executions.db 本任务今日错误。只读。"""
import sqlite3, os

SD = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(os.path.join(SD, 'ledger.db'))
c.row_factory = sqlite3.Row

t = c.execute("SELECT type, sql FROM sqlite_master WHERE name='strategy_accounts'").fetchone()
print('strategy_accounts type/sql:', t['type'], (t['sql'] or '')[:200])

rows = c.execute("""SELECT * FROM strategy_accounts WHERE REPLACE(date,'-','')='20260914'
                    ORDER BY account_id""").fetchall()
print('=== 20260914 NAV rows ===')
for r in rows:
    d = dict(r)
    resid = d['cash'] + d['pos_value'] - d['nav']
    print(f"{d['account_id']:14s} nav={d['nav']:.2f} cash={d['cash']:.2f} pos={d['pos_value']:.2f} "
          f"resid={resid:.4f} n_pos={d['n_pos']} daily={d['daily_ret']}")
print('count:', len(rows))

print('=== 各账户最新日期 ===')
for r in c.execute("""SELECT account_id, MAX(REPLACE(date,'-','')) mx, COUNT(*) n
                      FROM strategy_accounts GROUP BY account_id ORDER BY account_id"""):
    print(dict(r))

# 持仓估值日 (peaks/stops 更新)
print('=== 今日 trade_log 计数 ===')
print(c.execute("SELECT COUNT(*) FROM trade_log WHERE REPLACE(trade_date,'-','')='20260914'").fetchone()[0])

# executions.db
ep = os.path.expanduser('~/.hermes/cron/executions.db')
e = sqlite3.connect(ep)
e.row_factory = sqlite3.Row
cols = [r[1] for r in e.execute("PRAGMA table_info(executions)").fetchall()]
print('executions cols:', cols)
q = """SELECT * FROM executions WHERE job_id='051af215dc32'
       AND REPLACE(started_at,'-','') >= '20260914' ORDER BY started_at DESC LIMIT 15"""
for r in e.execute(q):
    d = dict(r)
    print({k: d[k] for k in ('job_id', 'started_at', 'status', 'error') if k in d})
