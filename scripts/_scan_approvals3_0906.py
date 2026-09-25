import re, collections
files = ['/Users/zantao/.hermes/logs/agent.log','/Users/zantao/.hermes/logs/agent.log.1','/Users/zantao/.hermes/logs/agent.log.2',
 '/Users/zantao/.hermes/logs/gateway.log','/Users/zantao/.hermes/logs/errors.log','/Users/zantao/.hermes/logs/errors.log.1']
first = collections.OrderedDict()
for f in files:
    try: txt = open(f, errors='ignore').read()
    except Exception: continue
    for m in re.finditer(r'Hardline block: command parser limit[^\n]{0,200}', txt):
        seg = m.group(0)
        cm = re.search(r'\(command: ?(.{0,150})', seg)
        if cm:
            c = cm.group(1).replace('\\n',' ')
            op = c.split()[0] if c else '?'
            if op not in first: first[op] = c[:150]
    for m in re.finditer(r'(launchctl|osascript|sudo)[^.\n]{0,80}(approv|denied|gate|block)[^\n]{0,80}', txt, re.I):
        k = 'gate:'+m.group(0)[:60]
        if k not in first: first[k]=m.group(0)[:140]
for k,v in first.items(): print('*',k,'=>',v)