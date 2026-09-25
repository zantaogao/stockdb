import json, sqlite3, os
c = sqlite3.connect('ledger.db')
rows = c.execute("SELECT account, code, ex_date, cash_div, tax_rate, shares_add, net_div FROM ca_adjustments").fetchall()
for r in rows: print(r)
print('---')
for f in sorted(os.listdir('sim_accounts')):
    if not f.endswith('.json') or f == 'main.json':
        continue
    aid = f[:-5]
    d = json.load(open('sim_accounts/' + f))
    if not isinstance(d.get('positions'), list) or 'cash' not in d:
        continue
    cash = d.get('initial_capital', 1000000.0)
    for t in d.get('trades', []):
        if t.get('action') == '买入':
            cash -= t.get('shares', 0) * t.get('price', 0)
        elif t.get('action') == '卖出':
            cash += t.get('shares', 0) * t.get('price', 0)
    ca = c.execute("SELECT COALESCE(SUM(net_div),0) FROM ca_adjustments WHERE account=?", (aid,)).fetchone()[0]
    print(f"{aid}: 无ca重建={cash:.1f} ca合计net_div={ca:.1f} JSONcash={d['cash']:.1f} 差(无ca-JSON)={cash - d['cash']:.1f}")