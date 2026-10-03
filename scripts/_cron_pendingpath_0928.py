import re
src = open('/Users/zantao/.hermes/stockdb/scripts/intraday_decision.py').read()
for i,l in enumerate(src.splitlines(),1):
    if 'PENDING_FILE' in l or 'exists()' in l and 'PENDING' in l.upper():
        print(i, l.strip()[:150])
print('---')
i = src.find('PENDING_FILE.exists')
# check if there's early-exit before pending write (e.g. skip if no signals path)
seg = src[src.find('def main'):src.find('def main')+3000]
for i,l in enumerate(seg.splitlines()):
    if 'exit' in l or 'return' in l or 'PENDING' in l or '跳过' in l:
        print(l.strip()[:150])
