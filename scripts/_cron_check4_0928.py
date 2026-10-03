import json, subprocess, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from agent_trade_decision import fetch_prices_batch
codes = ['600785','300228','600594','603737','002208','688500','001366','600510','000617','300732','603887','603113','300214']
px = fetch_prices_batch(codes)
print(json.dumps(px, ensure_ascii=False))
