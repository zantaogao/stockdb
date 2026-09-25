import json, os
path = os.path.expanduser('~/.hermes/stockdb/account.json')
d = json.loads(open(path).read())
print(f"Cash: {d.get('cash', 'N/A')}")
print(f"Initial capital: {d.get('initial_capital', 'N/A')}")
print(f"Holdings count: {len(d.get('holdings', []))}")
print(f"Trades count: {len(d.get('trades', []))}")
print()
# Read score cache
sc_path = os.path.expanduser('~/.hermes/stockdb/_score_cache.json')
if os.path.exists(sc_path):
    sc = json.loads(open(sc_path).read())
    print(f"Score cache date: {sc.get('date')}, version: {sc.get('_version')}")
    scores = sc.get('scores', {})
    # Check scores for hold/watch stocks
    codes = ['300475','688766','603156','603697','002832','002283','603061','601168','603726',
             '603045','688111','603706','002768','000506','002275',
             '688525','002039','300723']
    for c in codes:
        if c in scores:
            s = scores[c]
            print(f"  {c}: fusion={s.get('fusion')} reg20={s.get('reg20')} reg40={s.get('reg40')}")
        else:
            print(f"  {c}: no score")
else:
    print("No score cache found")
