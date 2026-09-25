# The script itself never emits 'Script execution failed' — the Hermes cron
# scheduler wraps exceptions with that prefix. Find the hermes source location
# and check how stdout is decoded (text=True without errors= => strict UTF-8).
import subprocess, glob

# Find hermes agent source
cands = glob.glob('/Users/zantao/.hermes/hermes*') + glob.glob('/Users/zantao/hermes*') + \
        subprocess.run(['pip', 'show', 'hermes-agent'], capture_output=True, text=True).stdout.split('Location:')[-1:]
print('hermes source:', cands[:5])

# Check the scheduler's communicate decode path — reproduce the exact error
# The warning string '⚠️ backfill_stk_factor.py 失败 exit=1（...' — byte 42 is 0xbc.
# Under what decode does ONLY position 42 fail? errors='ignore' style? No:
# strict decode reports the FIRST error = position 42. So the stdout stream
# at 22:00 began with text whose first invalid UTF-8 byte is the 0xbc of '失'.
# => The warning WAS the stdout the scheduler tried to decode. Reproduce:
s = '⚠️ backfill_stk_factor.py 失败 exit=1（因子未更新）'
b = s.encode('utf-8')
print('first bad byte of truncated copy ending at 失?:')
# If stdout got truncated mid-'失' and stderr merged... test truncations
for cut in range(40, 50):
    t = b[:cut]
    try:
        t.decode('utf-8')
    except UnicodeDecodeError as e:
        if e.start == 42:
            print('cut', cut, '=>', e)