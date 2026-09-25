import json, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.unified_account import AccountStore
s = AccountStore()
a = s.load('agent_auto')
print('cash', round(a.cash, 2), 'npos', len(a.positions))
for p in a.positions:
    print(p.code, p.name, p.shares, p.avg_cost, p.buy_date)
print('---')
b = s.load('center_dual')
print('center_dual cash', round(b.cash, 2), 'npos', len(b.positions))
for p in b.positions:
    print(p.code, p.name, p.shares, p.avg_cost, p.buy_date)
