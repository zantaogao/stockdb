import sys, sqlite3
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
from core.prices import _fetch_sina

con = sqlite3.connect(str(BASE / 'ledger.db'))
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute('SELECT * FROM holdings')]
peaks = {r[0]: r[1] for r in con.execute('SELECT code, peak_price, updated_at FROM position_peaks').fetchall()}
con.close()
q = _fetch_sina([str(h['code']) for h in rows])

print('%-8s %-6s %7s %7s %7s %7s %7s %8s' % ('code', '名称', '现价', '执行止损', '距止损%', '回撤线(峰×0.92)', '距回撤%', '目标价'))
out = []
for h in rows:
    c = str(h['code'])
    px = (q.get(c) or {}).get('price')
    if not px:
        continue
    cost = h['avg_cost']
    eff = min(h['stop_loss'], cost * 0.94) if h['stop_loss'] and cost else 0
    pk = peaks.get(c)
    line = pk * 0.92 if pk else 0
    tp = h['target_price'] or 0
    d_stop = (px / eff - 1) * 100 if eff else 99
    d_dd = (px / line - 1) * 100 if line else 99
    out.append((min(d_stop, d_dd), c, h['name'], px, eff, d_stop, line, d_dd, tp, pk, cost))
out.sort()
for _, c, nm, px, eff, ds, line, dd, tp, pk, cost in out:
    print('%-8s %-6s %7.2f %7.2f %+7.1f %10.2f %+8.1f %8.2f   峰值%s 成本%.2f' % (
        c, (nm or '')[:4], px, eff, ds, line, dd, tp, ('%.2f' % pk) if pk else '-', cost))
print('\n已跌破回撤止盈线(等大盘≤-2%才卖):')
for _, c, nm, px, eff, ds, line, dd, tp, pk, cost in out:
    if dd <= 0:
        print('  %s %s 现价%.2f < 回撤线%.2f (%+.1f%%)' % (c, nm, px, line, dd))
print('已跌破执行止损线:')
for _, c, nm, px, eff, ds, line, dd, tp, pk, cost in out:
    if ds <= 0:
        print('  %s %s 现价%.2f <= 止损%.2f (%+.1f%%)' % (c, nm, px, eff, ds))
