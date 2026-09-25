import subprocess

r = subprocess.run(['ps', '-ax', '-ww', '-o', 'pid,etime,%cpu,stat,command'], capture_output=True, text=True)
for l in r.stdout.splitlines():
    if ('agents/' in l or 'scripts/' in l or 'new_factors' in l or 'fusion' in l or 'signal' in l or 'tushare' in l) and 'grep' not in l:
        print(l[:160])