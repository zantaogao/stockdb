import json
d = json.load(open('/Users/zantao/.hermes/stockdb/data/trade_cal.json'))
dates = set(d['is_open_dates'])
for dt in ['20260929','20260930','20261001','20261002','20261005','20261006','20261007','20261008','20261009']:
    print(dt, 'OPEN' if dt in dates else 'closed')
