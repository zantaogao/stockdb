import sqlite3, os
LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(LED); con.row_factory = sqlite3.Row
print("=== 各账户现金占NAV比 (最近8个交易日) ===")
rows = list(con.execute("""SELECT account_id, date, nav, cash, pos_value, n_pos FROM strategy_accounts_legacy
                           WHERE REPLACE(date,'-','')>='20260903' ORDER BY date DESC, account_id"""))
import collections
by_date = collections.defaultdict(list)
for r in rows: by_date[r['date']].append(dict(r))
for d in sorted(by_date, reverse=True):
    line = []
    for r in sorted(by_date[d], key=lambda x: x['account_id']):
        cr = r['cash']/r['nav']*100 if r['nav'] else 0
        line.append(f"{r['account_id']}:{cr:.0f}%(n={r['n_pos']})")
    print(d, "  ".join(line))
print("\n=== 今日成交笔数按账户 (含时间) ===")
for r in con.execute("""SELECT strategy, direction, code, price, quantity, trade_time FROM trade_log
                        WHERE REPLACE(trade_date,'-','')>='20260911' ORDER BY trade_date, trade_time"""):
    print(dict(r))
