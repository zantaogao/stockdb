import json, os
path = os.path.expanduser('~/.hermes/stockdb/holdings.json')
d = json.loads(open(path).read())
counts = {}
for p in d.get('positions', []):
    s = p.get('status','?')
    counts[s] = counts.get(s, 0) + 1
print('Status counts:', json.dumps(counts))
print()
for p in d.get('positions', []):
    s = p.get('status','')
    print(f"  [{s}] {p.get('code')} {p.get('name')} buy={p.get('buy_price')} sl={p.get('stop_loss')} target={p.get('target')} entry={p.get('entry_low')}~{p.get('entry_high')}")
