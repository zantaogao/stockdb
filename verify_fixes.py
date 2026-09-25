#!/usr/bin/env python3
"""启动服务器线程，测试所有接口"""
import sys, threading, time, subprocess, json

BASE = '/Users/zantao/.hermes/stockdb'
sys.path.insert(0, BASE)

from server_multi_account import main as server_main

# Start server in thread
t = threading.Thread(target=server_main, daemon=True)
t.start()
time.sleep(3)  # Wait for server to be ready

# Test each endpoint
endpoints = [
    'http://127.0.0.1:8081/api/all_accounts',
    'http://127.0.0.1:8081/api/health',
    'http://127.0.0.1:8081/api/account?id=main',
    'http://127.0.0.1:8081/api/account?id=short',
    'http://127.0.0.1:8081/api/account?id=sim',
    'http://127.0.0.1:8081/api/cross_report',
    'http://127.0.0.1:8081/api/signals',
    'http://127.0.0.1:8081/api/all_nav_history',
    'http://127.0.0.1:8081/api/status',
    'http://127.0.0.1:8081/detail?code=300475',
    'http://127.0.0.1:8081/',
]

all_ok = True
for url in endpoints:
    r = subprocess.run(
        ['curl', '-s', '--max-time', '5', url],
        capture_output=True, text=True, timeout=10
    )
    path = url.split('127.0.0.1:8081')[1] or '/'
    if r.returncode != 0 or len(r.stdout) == 0:
        print('FAIL: %s (exit=%d, size=0)' % (path, r.returncode))
        all_ok = False
    else:
        print('OK:   %s (%d bytes)' % (path, len(r.stdout)))

# Test /api/run_engine POST
print('')
print('--- /api/run_engine POST (timeout 30s) ---')
r = subprocess.run(
    ['curl', '-s', '-X', 'POST', '--max-time', '30',
     'http://127.0.0.1:8081/api/run_engine'],
    capture_output=True, text=True, timeout=35
)
if r.returncode == 0 and len(r.stdout) > 0:
    try:
        d = json.loads(r.stdout)
        print('OK: /api/run_engine (%d bytes)' % len(r.stdout))
        if 'status' in d:
            print('  status: %s' % d.get('status'))
    except:
        print('OK: /api/run_engine (%d bytes, text response)' % len(r.stdout))
else:
    print('FAIL: /api/run_engine (exit=%d, size=%d)' % (r.returncode, len(r.stdout)))
    all_ok = False

# Test /api/all_accounts for real PnL data
print('')
print('--- Checking PnL data in /api/all_accounts ---')
r = subprocess.run(
    ['curl', '-s', '--max-time', '5', 'http://127.0.0.1:8081/api/all_accounts'],
    capture_output=True, text=True, timeout=10
)
if r.returncode == 0:
    try:
        d = json.loads(r.stdout)
        accounts = d.get('accounts', {})
        for aid, acct in accounts.items():
            print('  %s: %d positions' % (aid, len(acct.get('positions', []))))
            for p in acct.get('positions', []):
                pnl = p.get('pnl_pct', 'MISSING')
                print('    %s %s: cost=%.2f pnl=%s%%' % (p['code'], p.get('name','?'), p.get('avg_cost',0), pnl))
    except Exception as e:
        print('  ERROR: %s' % e)

# Check /api/account detail
print('')
print('--- Checking /api/account?id=main detail ---')
r = subprocess.run(
    ['curl', '-s', '--max-time', '5', 'http://127.0.0.1:8081/api/account?id=main'],
    capture_output=True, text=True, timeout=10
)
if r.returncode == 0:
    try:
        d = json.loads(r.stdout)
        nav_hist = d.get('nav_history', [])
        print('  nav_history entries: %d' % len(nav_hist))
        if nav_hist:
            # Check if it returns ALL entries (not just 30 or 60)
            print('  first: %s last: %s' % (nav_hist[0].get('date','?'), nav_hist[-1].get('date','?')))
    except Exception as e:
        print('  ERROR: %s' % e)

print('')
if all_ok:
    print('=== ALL TESTS PASSED ===')
else:
    print('=== SOME TESTS FAILED ===')
    sys.exit(1)
