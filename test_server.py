#!/usr/bin/env python3
"""Test server - starts it as a thread, hits all endpoints, reports results."""
import sys, threading, time, subprocess, json

BASE = '/Users/zantao/.hermes/stockdb'
sys.path.insert(0, BASE)

from server_multi_account import main as server_main

# Start server in thread
t = threading.Thread(target=server_main, daemon=True)
t.start()
time.sleep(2)  # Wait for server to be ready

# Verify server is running
r = subprocess.run(['lsof', '-i', ':8081'], capture_output=True, text=True, timeout=5)
if '8081' not in r.stdout:
    print("SERVER NOT LISTENING on :8081")
    print(r.stdout)
    sys.exit(1)

print("Server is running on :8081\n")

# Test each endpoint
endpoints = [
    ('GET', 'http://127.0.0.1:8081/api/all_accounts'),
    ('GET', 'http://127.0.0.1:8081/api/health'),
    ('GET', 'http://127.0.0.1:8081/api/account?id=main'),
    ('GET', 'http://127.0.0.1:8081/api/account?id=short'),
    ('GET', 'http://127.0.0.1:8081/api/account?id=sim'),
    ('GET', 'http://127.0.0.1:8081/api/cross_report'),
    ('GET', 'http://127.0.0.1:8081/api/signals'),
    ('GET', 'http://127.0.0.1:8081/api/all_nav_history'),
    ('GET', 'http://127.0.0.1:8081/api/status'),
    ('GET', 'http://127.0.0.1:8081/detail?code=300475'),
    ('GET', 'http://127.0.0.1:8081/'),
]

for method, url in endpoints:
    r = subprocess.run(
        ['curl', '-s', '-o', '/tmp/stockdb_resp', '-w', '%{http_code} %{size_download}'],
        capture_output=True, text=True, timeout=10
    )
    parts = r.stdout.strip().split()
    status = parts[0] if len(parts) > 0 else '???'
    size = parts[1] if len(parts) > 1 else '0'
    ok = 'OK' if status == '200' else 'FAIL'
    path = url.split('127.0.0.1:8081')[1] or '/'
    print('%-4s %s %s' % (ok, status, path))

# Test run_engine POST with timeout
print('')
print('--- testing /api/run_engine POST ---')
r = subprocess.run(
    ['curl', '-s', '-o', '/tmp/stockdb_resp', '-w', '%{http_code} %{size_download}',
     '-X', 'POST', '--max-time', '30',
     'http://127.0.0.1:8081/api/run_engine'],
    capture_output=True, text=True, timeout=35
)
status = r.stdout.strip()
print('  Status/Size: %s' % status)
if r.returncode == 0 and status.split()[0] == '200':
    print('  ✅ run_engine succeeded')
else:
    print('  ❌ run_engine failed')

# Print any server errors from process log
print('')
print('--- Server log (last 20 lines) ---')
