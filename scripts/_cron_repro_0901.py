import subprocess, sys

# Simulate the script's exact error path: subprocess with LANG unset capturing a
# GBK/CP936 error from Python 3.9 (which on macOS uses the C locale filesystem encoding)
env = {'PATH': '/usr/bin:/bin'}  # no LANG, no PYTHONUTF8, no PYTHONIOENCODING
code = "import sys; sys.stdout.buffer.write('⚠️ backfill_stk_factor.py 失败 exit='.encode('utf-8'))"
r = subprocess.run([sys.executable, '-c', code], capture_output=True, env=env)
b = r.stdout
print('bytes:', b[:60].hex())
print('byte at 42:', hex(b[42]) if len(b) > 42 else 'n/a')
try:
    b.decode('utf-8')
    print('decodes fine')
except UnicodeDecodeError as e:
    print('DECODE ERR:', e)
    print('as GBK:', b.decode('gbk', errors='replace')[:50])