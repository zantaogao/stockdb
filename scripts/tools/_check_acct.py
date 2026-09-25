import json, os
path = os.path.expanduser('~/.hermes/stockdb/account.json')
d = json.loads(open(path).read())
print('=== HOLDINGS ===')
for h in d.get('holdings', []):
    print(f"  {h.get('code')} {h.get('name')} cost={h.get('avg_cost')} shares={h.get('shares')} val={h.get('market_value')}")
print('=== TRADES (last 8) ===')
for t in d.get('trades', [])[-8:]:
    print(f"  {t.get('date')} {t.get('action')} {t.get('code')} {t.get('name')} @{t.get('price')} x{t.get('shares')} pnl={t.get('pnl','')}")
