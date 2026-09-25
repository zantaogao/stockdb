import json, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.prices import fetch_prices_batch
codes = ['001238','300837','300881','301053','301338','301538','603409','688592','688607','300500','603382']
print(fetch_prices_batch(codes))
