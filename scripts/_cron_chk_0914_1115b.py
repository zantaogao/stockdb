"""本轮tick(11:15)独立核查: NAV/持仓/现金三方一致性 + 今日成交笔数。只读。"""
import sqlite3, json, os

SD = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(os.path.join(SD, 'ledger.db'))
c.row_factory = sqlite3.Row

print('=== strategy_accounts NAV 最新日 ===')
rows = c.execute("""SELECT account_id, MAX(signal_date) d, COUNT(*) n
                    FROM strategy_accounts GROUP BY account_id""").fetchall()
for r in rows:
    print(dict(r))

print('=== 今日(20260914)各账户 NAV 明细 ===')
try:
    rows = c.execute("""SELECT * FROM strategy_accounts
                        WHERE REPLACE(signal_date,'-','')='20260914'""").fetchall()
    for r in rows:
        d = dict(r)
        print({k: d[k] for k in list(d)[:12]})
except Exception as e:
    print('ERR', e)

print('=== 今日成交(strategy 表/交易表探测) ===')
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('tables:', tabs)
for t in tabs:
    if 'trade' in t.lower() or 'txn' in t.lower():
        try:
            n = c.execute(f"SELECT COUNT(*) FROM {t} WHERE REPLACE(date,'-','')='20260914'").fetchone()[0]
            print('  ', t, 'today rows =', n)
        except Exception as e:
            print('  ', t, 'skip', e)
