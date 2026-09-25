import glob, os, subprocess

# Scan stockdb text files: which have byte42 == 0xbc?
hits = []
for f in glob.glob('/Users/zantao/.hermes/stockdb/**/*.sh', recursive=True) + \
         glob.glob('/Users/zantao/.hermes/scripts/*.sh'):
    b = open(f, 'rb').read(60)
    if len(b) > 42 and b[42] == 0xbc:
        hits.append(f)
        print('HIT:', f)
        print('   text:', b.decode('utf-8', errors='replace')[30:60])

# Check cron log lines around 22:00:19
log = open('/Users/zantao/.hermes/logs/agent.log', encoding='utf-8', errors='replace').read().splitlines()
in_window = [l for l in log if '2026-09-01 22:0' in l and ('099aee' in l or 'script' in l.lower())]
for l in in_window[:10]:
    print(l[:200])