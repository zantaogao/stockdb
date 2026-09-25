import sys, sqlite3
from pathlib import Path
from datetime import datetime

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
from core.prices import _fetch_sina
import duckdb

PREV = '20260914'
d = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
con = sqlite3.connect(str(BASE / 'ledger.db'))
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute("SELECT * FROM holdings WHERE status='holding' OR status IS NULL") ]
rows = [dict(r) for r in con.execute('SELECT * FROM holdings')]
cash = con.execute("SELECT cash_balance FROM account_balance WHERE account_id='main'").fetchone()[0]
peaks = {r[0]: r[1] for r in con.execute('SELECT * FROM position_peaks').fetchall()}
con.close()

prev_close = {}
codes = [str(h['code']) for h in rows]
for c in codes:
    ts = c + ('.SH' if c.startswith(('6', '9')) else '.SZ')
    r = d.execute('SELECT close FROM daily WHERE ts_code=? AND trade_date=?', [ts, PREV]).fetchone()
    prev_close[c] = r[0] if r else None
d.close()

q = _fetch_sina(codes)
print('时间:', datetime.now().strftime('%H:%M:%S'), ' 基准昨收日:', PREV)
print('%-9s %-7s %7s %7s %7s %7s %8s %10s %8s %8s %7s' % ('code', 'name', '成本', '昨收', '现价', '今涨%', '浮盈%', '上午盈亏元', '扫描止损', '有效止损', '距有效%'))
tot_prev_val = tot_now_val = 0.0
rank = []
for h in rows:
    c = str(h['code'])
    px = (q.get(c) or {}).get('price')
    pc = prev_close.get(c)
    if not px or not pc:
        print('%s 缺价 px=%s pc=%s' % (c, px, pc))
        continue
    sh = h['shares']
    tot_prev_val += sh * pc
    tot_now_val += sh * px
    delta = sh * (px - pc)
    eff = min(h['stop_loss'], h['avg_cost'] * 0.94) if h['stop_loss'] and h['avg_cost'] else None
    rank.append((delta, c, h['name']))
    print('%-9s %-7s %7.2f %7.2f %7.2f %+7.2f %+8.2f %+10.0f %8.2f %8.2f %+7.1f' % (
        c, (h['name'] or '')[:5], h['avg_cost'], pc, px, (px / pc - 1) * 100,
        (px / h['avg_cost'] - 1) * 100, delta, h['stop_loss'] or 0, eff or 0,
        (px / eff - 1) * 100 if eff else 0))

print('\n持仓市值 %.0f → %.0f  变化 %+.0f 元 (%.2f%%)' % (tot_prev_val, tot_now_val,
      tot_now_val - tot_prev_val, (tot_now_val / tot_prev_val - 1) * 100))
tot_prev, tot_now = cash + tot_prev_val, cash + tot_now_val
print('账户总资产 %.0f → %.0f  (%+.0f 元, %+.2f%%)   现金 %.0f (%.1f%%仓位)' % (
    tot_prev, tot_now, tot_now - tot_prev, (tot_now / tot_prev - 1) * 100, cash, (1 - cash / tot_now) * 100))
print('现金占比 %.1f%%' % (cash / tot_now * 100))
rank.sort()
print('\n上午拖累前三:', ' | '.join('%s %s %+.0f元' % (c, n, dl) for dl, c, n in rank[:3]))
print('上午贡献前三:', ' | '.join('%s %s %+.0f元' % (c, n, dl) for dl, c, n in rank[-3:]))
