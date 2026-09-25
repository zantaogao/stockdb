import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db')
c.row_factory = sqlite3.Row
print('=== 20260914 活跃账户: NAV vs cash+pos + n_pos vs 持仓行数 ===')
for r in c.execute("SELECT account_id,date,nav,cash,pos_value,daily_ret,n_pos,created_at FROM strategy_accounts WHERE date='20260914' ORDER BY account_id").fetchall():
    d = dict(r)
    nrows = c.execute("SELECT COUNT(*) FROM strategy_positions WHERE account_id=?", (d['account_id'],)).fetchone()[0]
    diff = round(d['cash'] + d['pos_value'] - d['nav'], 4)
    print(f"{d['account_id']:13s} NAV={d['nav']:.0f} cash+pos={d['cash']+d['pos_value']:.0f} diff={diff} n_pos={d['n_pos']} rows={nrows} ret={d['daily_ret']} written={d['created_at']}")
print('\n=== 本tick(10:26)之后是否有新成交 ===')
for r in c.execute("SELECT id,code,direction,price,quantity,trade_date,trade_time,strategy FROM trade_log WHERE REPLACE(trade_date,'-','')='20260914' ORDER BY id").fetchall():
    print(dict(r))
print('\n=== 同日重复行检查 ===')
for r in c.execute("SELECT account_id,date,COUNT(*) FROM strategy_accounts WHERE date='20260914' GROUP BY account_id,date HAVING COUNT(*)>1").fetchall():
    print('DUP', tuple(r))
print('无重复输出即OK')
