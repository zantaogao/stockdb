import sqlite3, json
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
codes3f = ['600395','601001','600403','600198','601991']
codes_dual = ['300036','002972','001260','601615','002565','000545','300444','300511','300772','603279','603585','603665']
for f, codes in (('fusion3f', codes3f), ('fusion_dual', codes_dual)):
    d = json.load(open(f'/Users/zantao/.hermes/stockdb/sim_accounts/{f}.json'))
    print('='*20, f, 'cash:', d.get('cash'), 'initial:', d.get('initial_capital'))
    for t in d.get('trades', []):
        if t.get('code') in codes and str(t.get('date','')) >= '2026-09-01':
            print('  trade:', t)
    print('  positions:', [(x.get('code'), x.get('shares'), x.get('buy_date')) for x in d.get('positions', []) if x.get('code') in codes])
print('null-id rows:', c.execute("SELECT COUNT(*) FROM trade_log WHERE id IS NULL").fetchone())
print('max non-null id:', c.execute("SELECT MAX(id) FROM trade_log WHERE id IS NOT NULL").fetchone())
print(c.execute("SELECT sql FROM sqlite_master WHERE name='trade_log'").fetchone()[0])
# what strategy names exist in JSON trade entries for these accounts around 0916?
for f in ('fusion3f','fusion_dual'):
    tl = c.execute("SELECT code,direction,price,quantity,trade_date,trade_time,strategy FROM trade_log WHERE strategy=? AND REPLACE(trade_date,'-','')>='20260915' ORDER BY trade_date,trade_time", (f,)).fetchall()
    print('--- trade_log', f)
    for r in tl: print('  ', r)
