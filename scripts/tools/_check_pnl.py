import json, os

BASE = os.path.expanduser('~/.hermes/stockdb')

with open(os.path.join(BASE, 'holdings.json')) as f:
    holdings = json.load(f)

# Compute PnL using buy_price from holdings
pnls = {}
for p in holdings['positions']:
    if p.get('status') == 'hold' and p.get('buy_price'):
        pnls[p['code']] = p['buy_price']

print('Buy prices for holdings:')
for c, bp in pnls.items():
    print(f'{c}: buy={bp}')
