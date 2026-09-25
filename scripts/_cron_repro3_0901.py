# Test candidate strings for byte42 == 0xbc under a non-strict decode path
cands = {
    'script': 'backfill_stk_factor.sh',
    'script_abs': '/Users/zantao/.hermes/scripts/backfill_stk_factor.sh',
    'bash_line': '/bin/bash /Users/zantao/.hermes/scripts/backfill_stk_factor.sh',
    'session': 'cron_099aee371ab5_20260901_225545',
}
for name, s in cands.items():
    b = s.encode('utf-8')
    print(name, 'len', len(b), 'byte42', hex(b[42]) if len(b) > 42 else 'n/a')

# The error text 'position 42' with byte 0xbc: which strings have a CJK char
# starting exactly at byte 42 when they contain replacement chars?
# Check: decode with errors='ignore' roundtrip of the shell warning
import subprocess
r = subprocess.run(['/bin/bash', '-c', 'echo "⚠️ backfill_stk_factor.py 失败 exit=$RC（因子未更新，信号用现有因子重算，保证当天有信号）"'],
                   capture_output=True)
b = r.stdout
print('warn bytes len:', len(b))
# find 0xbc positions
print('0xbc at:', [i for i, x in enumerate(b) if x == 0xbc][:5])
# now what if stderr/stdout was decoded as gbk then re-encoded
try:
    b.decode('utf-8')
    print('warn stdout decodes utf-8 fine')
except UnicodeDecodeError as e:
    print('warn decode err', e)