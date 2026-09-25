import re, collections, glob
pat_cmd = collections.Counter()
for f in ['/Users/zantao/.hermes/logs/agent.log','/Users/zantao/.hermes/logs/agent.log.1','/Users/zantao/.hermes/logs/agent.log.2','/Users/zantao/.hermes/logs/errors.log','/Users/zantao/.hermes/logs/errors.log.1']:
    try:
        txt = open(f, errors='ignore').read()
    except Exception:
        continue
    for m in re.finditer(r'(?i)(requires? approval|required approval|pending approval|blocked[^\n]{0,40}approv)[^\n]{0,400}', txt):
        seg = m.group(0)
        cm = re.search(r'\(command: ?(.{0,120})', seg)
        key = cm.group(1)[:100] if cm else seg[:100]
        pat_cmd[key.split(',')[0].strip()] += 1
for k,v in pat_cmd.most_common(30):
    print(v, '|', k)