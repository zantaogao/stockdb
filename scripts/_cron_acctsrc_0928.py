import subprocess, glob, os, time
src = open('/Users/zantao/.hermes/stockdb/agents/exec_agent.py').read()
i = src.find('def load_account')
print(src[i:i+700] if i>=0 else 'no load_account func')
for m in ('ACCOUNT','account_file','accounts/'):
    idx = src.find('accounts')
    if idx>=0:
        print('...',src[idx-100:idx+200])
        break
