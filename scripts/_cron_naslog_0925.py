import re, os
p = os.path.expanduser('~/.hermes/logs/nas_backup.log')
lines = open(p, errors='replace').read().splitlines()
runs = []
cur = None
for i, l in enumerate(lines):
    if l.startswith('===== NAS 备份'):
        if cur:
            runs.append(cur)
        cur = {'header': l, 'idx': i, 'tail': []}
    elif cur is not None:
        cur['tail'].append(l)
if cur:
    runs.append(cur)
print(f'总运行次数(有header): {len(runs)}')
for r in runs[-8:]:
    tail = [x for x in r['tail'] if x.strip()][-3:]
    print('---', r['header'])
    for x in tail:
        print('   ', x[:160])
