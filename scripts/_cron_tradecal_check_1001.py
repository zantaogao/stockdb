import json
data = json.load(open('/Users/zantao/.hermes/stockdb/data/trade_cal.json'))
print('generated_at:', data['generated_at'], 'source:', data['source'], 'range:', data['range'], 'n:', data['n'])
dates = data['is_open_dates']
for d in ('20260930','20261001','20261002','20261008'):
    print(d, 'open' if d in dates else 'closed')
