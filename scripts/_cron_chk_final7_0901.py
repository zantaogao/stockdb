import subprocess, sqlite3

# 1) scheduler processes
r = subprocess.run(['ps', '-ax', '-ww', '-o', 'pid,lstart,etime,command'], capture_output=True, text=True)
for l in r.stdout.splitlines():
    low = l.lower()
    if ('gateway' in low or 'cron' in low or 'run_agent' in low or 'hermes' in low) and 'grep' not in low and 'ps -ax' not in low:
        print(l[:250])

# 2) what does signal_history 0901 look like (did the 18:xx chain produce it?)
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print()
print('signal_history 0901 sample:', sig.execute("SELECT stock_code, REPLACE(date,'-',''), strategy FROM signal_history WHERE REPLACE(date,'-','')='20260901' LIMIT 3").fetchall())
print('strategies in 0901:', sig.execute("SELECT DISTINCT strategy FROM signal_history WHERE REPLACE(date,'-','')='20260901'").fetchall())