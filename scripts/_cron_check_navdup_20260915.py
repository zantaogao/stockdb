import json, glob, os, collections, datetime
print("now:", datetime.datetime.now().isoformat())
for f in sorted(glob.glob(os.path.expanduser('~/.hermes/stockdb/sim_accounts/*.json'))):
    b = os.path.basename(f)
    if '.old' in b or '.err' in b:
        continue
    try:
        d = json.load(open(f))
    except Exception as e:
        print(b, 'ERR', e); continue
    h = d.get('nav_history') or []
    c = collections.Counter(str(x.get('date','')).replace('-','') for x in h)
    dup = {k: v for k, v in c.items() if v > 1}
    print(f"{b:22s} entries={len(h):4d} dups={dup} last2={[(x.get('date'), x.get('nav')) for x in h[-2:]]} mtime={datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime('%H:%M:%S')}")
