# Simulate the cron _run_job_script decode with a cleaned PATH (no /usr/bin),
# like the sanitized subprocess env might have
import subprocess, sqlite3

# What does the script emit when python3 is not found?
env = {'PATH': '/usr/local/bin:/bin:/usr/bin', 'HOME': '/Users/zantao'}
p = subprocess.run(['/bin/bash', '-c', '''cd /Users/zantao/.hermes/stockdb || exit 1
python3 -B scripts/backfill_stk_factor.py
RC=$?
if [ $RC -ne 0 ]; then
  echo "⚠️ backfill_stk_factor.py 失败 exit=$RC（因子未更新，信号用现有因子重算，保证当天有信号）"
fi'''], capture_output=True, env={'PATH': '/usr/bin:/bin', 'HOME': '/Users/zantao'}, timeout=30)
# Actually emulate missing python: PATH without python
b = p.stdout
print('rc', p.returncode, 'stdout len', len(b))
print('0xbc positions:', [i for i, x in enumerate(b) if x == 0xbc][:3])
try:
    b.decode('utf-8')
    print('decodes fine')
except UnicodeDecodeError as e:
    print('REPRO EXACT:', e)