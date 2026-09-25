import json, os, sqlite3
base = os.path.expanduser('~/.hermes/stockdb')
acts = ['agent_auto', 'center_dual', 'cmmr', 'cmmr_fusion', 'fusion_center']
for a in acts:
    p = f'{base}/sim_accounts/{a}.json'
    d = json.load(open(p))
    h = d.get('nav_history', [])
    norm = [x for x in h if str(x.get('date', '')).replace('-', '') in ('20260911', '20260914')]
    print(a, '| json rows 0911/0914:', json.dumps(norm[-3:], ensure_ascii=False))
    # dup check same-day (横杠归一)
    keys = {}
    for x in h:
        k = str(x.get('date', '')).replace('-', '')
        keys[k] = keys.get(k, 0) + 1
    dups = {k: v for k, v in keys.items() if v > 1}
    print('   dup_days:', dups)
    print('   positions:', len(d.get('positions', [])), 'cash:', d.get('cash'))
