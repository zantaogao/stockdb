#!/usr/bin/env python3
# 主账户逐票当日盈亏金额 + 累计盈亏（信号日0922）
import duckdb, os, sqlite3
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
cols = [d[1] for d in c.execute('PRAGMA table_info(holdings)').fetchall()]
print('holdings cols:', cols)
rows = c.execute('SELECT * FROM holdings').fetchall()
t = duckdb.connect('tushare.db', read_only=True)
codes = [r[cols.index('code' if 'code' in cols else 'stock_code')] for r in rows]
def suff(x):
    return x + ('.SH' if x.startswith(('6','9')) else '.SZ')
suffixed = [x if '.' in x else suff(x) for x in codes]
inl = ','.join("'" + x + "'" for x in suffixed)
px = {}
for tc, td, c1, c0 in t.execute(f"SELECT ts_code,trade_date,close,pre_close FROM daily WHERE ts_code IN ({inl}) AND trade_date>='20260915'").fetchall():
    if td == '20260922':
        px[tc] = (c1, c0)
prof = {}
for tc, close in t.execute(f"SELECT ts_code,close FROM daily WHERE ts_code IN ({inl}) AND trade_date=(SELECT MAX(trade_date) FROM daily WHERE trade_date<'20260922' AND ts_code!='')").fetchall():
    prof[tc] = close
tot = 0
res = []
for r in rows:
    d = dict(zip(cols, r))
    code = d.get('code') or d.get('stock_code')
    name = d.get('name', '')
    shares = d.get('shares') or 0
    cost = d.get('avg_cost') or d.get('cost_price') or 0
    p = px.get(code)
    if p:
        c1, c0 = p
        day = (c1 - c0) * shares
        cum = (c1 - cost) * shares
        tot += day
        res.append((day, name, code, shares, cost, c1, (c1/c0-1)*100, cum, d.get('buy_date','')))
res.sort(reverse=True)
print('%-8s %-10s %8s %8s %8s %7s %9s' % ('code','name','shares','cost','close','day%','dayPnL'))
for day, name, code, shares, cost, c1, pct, cum, bd in res:
    print('%-8s %-10s %8.0f %8.3f %8.3f %+6.2f %+9.0f cum=%+.0f buy=%s' % (code, name, shares, cost, c1, pct, day, cum, bd))
print('当日盈亏合计(有行情的):', round(tot,0))
# 账户现金
try:
    print('balance:', c.execute('SELECT * FROM account_balance').fetchall())
except Exception as e:
    print('bal err', e)
# 止损/止盈目标
try:
    wl = [d[1] for d in c.execute('PRAGMA table_info(watchlist)').fetchall()]
    print('watchlist cols:', wl)
    for r in c.execute('SELECT * FROM watchlist').fetchall()[:20]:
        print(r)
except Exception as e:
    print('wl err', e)
