import subprocess, json, sys

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
]

for method, url in endpoints:
    r = subprocess.run(
        ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code} %{size_download}'],
        capture_output=True, text=True, timeout=10
    )
    parts = r.stdout.strip().split()
    status = parts[0] if len(parts) > 0 else '???'
    size = parts[1] if len(parts) > 1 else '0'
    ok = 'OK' if status == '200' else 'FAIL'
    path = url.split('127.0.0.1:8081')[1] or '/'
    print('%s %s %s' % (ok, status, path))

# Test run_engine POST
print('--- testing /api/run_engine POST (timeout 30s) ---')
r = subprocess.run(
    ['curl', '-s', '-X', 'POST', '-o', '/dev/null', '-w', '%{http_code}',
     '--max-time', '30', 'http://127.0.0.1:8081/api/run_engine'],
    capture_output=True, text=True, timeout=35
)
print('  Status: %s' % r.stdout.strip())

# Test dashboard page
print('--- testing / (dashboard) ---')
r = subprocess.run(
    ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code} %{size_download}'],
    capture_output=True, text=True, timeout=10
)
print('  Status: %s' % r.stdout.strip())
