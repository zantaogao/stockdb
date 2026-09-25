import json, glob
for f in sorted(glob.glob('/Users/zantao/.hermes/stockdb/sim_accounts/*.json')):
    d = json.load(open(f))
    name = f.split('/')[-1].replace('.json','')
    navs = d.get('nav_history') or d.get('nav') or []
    last = navs[-1] if isinstance(navs, list) and navs else None
    print(name, '| keys:', list(d.keys())[:8], '| last_nav_entry:', last, '| n_history:', len(navs) if isinstance(navs,list) else '?')
