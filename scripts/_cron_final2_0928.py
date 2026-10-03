import json
from pathlib import Path
p = Path('/Users/zantao/.hermes/stockdb/orders/pending.json')
print('FINAL pending exists:', p.exists())
if p.exists():
    d = json.load(open(p))
    print(json.dumps(d, ensure_ascii=False, indent=1)[:1500])
