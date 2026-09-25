import re, glob, os
# find where the CLI renders the bottom status bar tokens: cache hit %, t/s, compaction count
pats = [r'compaction', r'compacted', r'ctx%', r'cache.hit', r'\bt/s\b', r'⚙', r'↻']
hits = {}
for root, dirs, files in os.walk('/Users/zantao/.hermes/hermes-agent/hermes_cli'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fn in files:
        if not fn.endswith('.py'): continue
        p = os.path.join(root, fn)
        try: txt = open(p, errors='ignore').read()
        except Exception: continue
        for pat in pats:
            for m in re.finditer(pat, txt):
                ln = txt.count('\n', 0, m.start()) + 1
                line = txt.split('\n')[ln-1].strip()[:150]
                key = (fn, pat)
                hits.setdefault(key, []).append((ln, line))
for (fn, pat), lst in sorted(hits.items()):
    if pat in (r'compaction', r'compacted') and 'status' not in pat:
        pass
    print('==', fn, pat, len(lst))
    for ln, line in lst[:4]:
        print('  ', ln, line)