import os, json, collections
os.chdir('/Users/zantao/.hermes/stockdb')
cnt = collections.Counter()
by_acct = collections.Counter()
rows = []
with open('analysis/opinion_log.jsonl') as f:
    for line in f:
        if '"2026-09-30' not in line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        k = j.get('key', '?')
        fam = k.split('|')[0]
        cnt[fam] += 1
        if fam in ('tgt', 'ddfuse', 'stoploss'):
            by_acct[k] += 1
        rows.append((j['ts'], fam, j.get('code', ''), j.get('text', '')[:60]))
print('family counts:', dict(cnt))
print('total morning opinions:', len(rows))
print('first:', rows[0][0] if rows else None, 'last:', rows[-1][0] if rows else None)
print('--- sell-side opinions (tgt/stoploss/ddfuse) ---')
for r in rows:
    if r[1] in ('tgt', 'stoploss', 'ddfuse'):
        print(r)
