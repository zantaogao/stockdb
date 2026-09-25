import json, sys
from pathlib import Path
from collections import OrderedDict

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
from core.prices import _fetch_sina

rows = []
for line in open(BASE / 'analysis/opinion_log.jsonl', encoding='utf-8'):
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    if str(d.get('ts', '')).startswith('2026-09-15'):
        rows.append(d)

first = OrderedDict()
for d in rows:
    k = d.get('key')
    code = str(d.get('code') or '')
    if not code:
        continue
    kind = (k or '').split('|')[0]
    if code not in first:
        first[code] = {'kind': kind, 't': d['ts'][11:16], 'px': d.get('price'), 'txt': d.get('text', '')[:60]}
    last = d
last_px = {str(d.get('code')): d.get('price') for d in rows if d.get('code')}

codes = [c for c in first if c]
q = _fetch_sina(codes)

print('=== 上午盘中意见复盘（首推价 → 11:30价）===')
print('%-8s %-4s %-5s %7s %7s %7s  %s' % ('code', 'kind', 'time', '首推价', '11:30', '变动%', '首推文本'))
groups = {}
for c, f in first.items():
    now = (q.get(c) or {}).get('price')
    if not now or not f['px']:
        continue
    chg = (now / f['px'] - 1) * 100
    groups.setdefault(f['kind'], []).append((chg, c, f, now))

for kind in ['buyzone', 'chase', 'stopbuy', 'nsl', 'sl']:
    lst = groups.get(kind, [])
    if not lst:
        continue
    avg = sum(x[0] for x in lst) / len(lst)
    win = sum(1 for x in lst if x[0] > 0)
    print('\n--- %s  共%d条 首推后平均%+.2f%%  上涨%d条(%.0f%%) ---' % (kind, len(lst), avg, win, win / len(lst) * 100))
    for chg, c, f, now in sorted(lst, reverse=True):
        print('%-8s %-4s %-5s %7.2f %7.2f %+7.2f  %s' % (c, kind, f['t'], f['px'], now, chg, f['txt']))

print('\n=== 跟踪重点（今日首推时间线）===')
for d in rows:
    if str(d.get('key', '')).split('|')[0] in ('buyzone', 'chase') and str(d.get('code')) in ('605222', '688545', '688059', '300274', '301053', '002585', '688004', '300916', '600246', '688217', '603226'):
        print(d['ts'][11:16], '|', d['text'][:110])
