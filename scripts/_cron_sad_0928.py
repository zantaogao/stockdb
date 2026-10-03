import glob, os, time
src = open('/Users/zantao/.hermes/stockdb/scripts/strategy_accounts_daily.py').read()
print('exec_agent mentioned:', 'exec_agent' in src)
print('pending.json mentioned:', 'pending.json' in src)
print('first 40 lines:')
print('\n'.join(src.splitlines()[:25]))
print('...')
print('mtime:', time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime('/Users/zantao/.hermes/stockdb/scripts/strategy_accounts_daily.py'))))
