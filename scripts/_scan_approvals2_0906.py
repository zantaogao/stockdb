import re, collections
files = glob_ = ['/Users/zantao/.hermes/logs/agent.log','/Users/zantao/.hermes/logs/agent.log.1','/Users/zantao/.hermes/logs/agent.log.2',
 '/Users/zantao/.hermes/logs/gateway.log','/Users/zantao/.hermes/logs/errors.log','/Users/zantao/.hermes/logs/errors.log.1']
cnt = collections.Counter()
samples = {}
for f in files:
    try: txt = open(f, errors='ignore').read()
    except Exception: continue
    # pattern: "Command required approval (CATEGORY) and was approved" or "requires approval (CATEGORY)"
    for m in re.finditer(r'required approval \(([^)]{1,80})\)', txt):
        cat = m.group(1)
        # grab the command text after, if any
        tail = txt[m.end():m.end()+300]
        cm = re.search(r'command[:=] ?(.{0,140})', tail)
        key = re.sub(r'\[.*?\]','',cat).strip()
        cnt[key]+=1
        if key not in samples and cm: samples[key]=cm.group(1)[:140]
    for m in re.finditer(r'Hardline block[^.\n]{0,120}', txt):
        cnt['HARDLINE: '+m.group(0)[:80]]+=1
for k,v in cnt.most_common(40):
    print(v,'|',k)
    if k in samples: print('    e.g.', samples[k])