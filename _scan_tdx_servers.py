#!/usr/bin/env python3
"""逐台测 pytdx 全服务器列表：连上+拉000001的1分钟线，看哪些真有数据。"""
import socket, time, sys
from pytdx.hq import TdxHq_API
from pytdx.config.hosts import hq_hosts

def probe(name, host, port, timeout=4):
    api = TdxHq_API()
    try:
        if not api.connect(host, port, time_out=timeout):
            return 'CONNECT_FAIL', 0
        # category=8 是 1分钟线 (0.000001 平安银行)
        data = api.get_security_bars(8, 0, '000001', 0, 48)
        api.disconnect()
        n = len(data) if data else 0
        if n:
            last = data[-1]
            return f'OK {n}行 最新={last[0]}', n
        return 'EMPTY', 0
    except Exception as e:
        try: api.disconnect()
        except Exception: pass
        return f'ERR {type(e).__name__}', 0

results = []
for name, host, port in hq_hosts:
    try:
        status, n = probe(name, host, port)
    except Exception as e:
        status, n = f'ERR {type(e).__name__}', 0
    results.append((status.startswith('OK'), n, status, name, host))
    print(f'{status:35s} {name:20s} {host}', flush=True)

# 也测脚本硬编码的两台
for host in ('218.75.126.9', '115.238.90.165'):
    status, n = probe('hardcoded', host, 7709)
    results.append((status.startswith('OK'), n, status, 'HARDCODED', host))
    print(f'{status:35s} {"HARDCODED":20s} {host}', flush=True)

ok = [r for r in results if r[0]]
print(f'\n===== 可用 {len(ok)}/{len(results)} =====')
for _, n, status, name, host in ok:
    print(f'  {host:18s} {name}  {status}')
