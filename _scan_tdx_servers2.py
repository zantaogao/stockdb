#!/usr/bin/env python3
"""测 mootdx HQ 服务器列表：连上+拉000001的1分钟线+日线，找出真正能返回数据的。"""
import sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pytdx.hq import TdxHq_API
from mootdx.server import hosts

def probe(host, port, timeout=4):
    api = TdxHq_API()
    try:
        if not api.connect(host, port, time_out=timeout):
            return (host, port, 'CONNECT_FAIL', 0, 0)
        m1 = api.get_security_bars(8, 0, '000001', 0, 48)   # 1分钟
        d1 = api.get_security_bars(9, 0, '000001', 0, 10)   # 日线
        api.disconnect()
        return (host, port, 'OK' if m1 else 'EMPTY', len(m1) if m1 else 0, len(d1) if d1 else 0)
    except Exception as e:
        try: api.disconnect()
        except Exception: pass
        return (host, port, f'ERR {type(e).__name__}', 0, 0)

targets = []
for h in hosts['HQ']:
    targets.append((h['addr'], int(h['port']), h.get('site', '')))
# 去重
seen, uniq = set(), []
for addr, port, site in targets:
    if (addr, port) not in seen:
        seen.add((addr, port)); uniq.append((addr, port, site))
print(f'探测 {len(uniq)} 台（mootdx HQ 列表）', flush=True)

rows = []
with ThreadPoolExecutor(max_workers=16) as ex:
    futs = {ex.submit(probe, a, p): (a, p, s) for a, p, s in uniq}
    for f in as_completed(futs):
        a, p, s = futs[f]
        host, port, status, n1, nd = f.result()
        rows.append((status, host, port, s, n1, nd))
        if status == 'OK':
            print(f'OK   {host}:{port}  1min={n1} 日线={nd}  {s}', flush=True)

rows.sort(key=lambda r: (r[0] != 'OK', r[1]))
with open('/tmp/tdx_mootdx_scan.tsv', 'w') as f:
    for r in rows:
        f.write('\t'.join(map(str, r)) + '\n')

ok = [r for r in rows if r[0] == 'OK']
empty = [r for r in rows if r[0] == 'EMPTY']
print(f'\n===== OK {len(ok)} | EMPTY {len(empty)} | 其他 {len(rows)-len(ok)-len(empty)} / {len(rows)} =====')
# 时间戳验证：OK 服务器的最新1分钟bar是哪天
for status, host, port, site, n1, nd in ok[:10]:
    api = TdxHq_API()
    try:
        if api.connect(host, port, time_out=4):
            bars = api.get_security_bars(8, 0, '000001', 0, 5)
            dbar = api.get_security_bars(9, 0, '000001', 0, 2)
            last1 = bars[-1]['datetime'] if bars else '-'
            lastd = dbar[-1]['datetime'] if dbar else '-'
            print(f'  {host:18s} {site:15s} 1min最新={last1}  日线最新={lastd}')
            api.disconnect()
    except Exception as e:
        print(f'  {host} recheck ERR {e}')
