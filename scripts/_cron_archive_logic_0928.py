import glob, os, time
src = open('/Users/zantao/.hermes/stockdb/agents/exec_agent.py').read()
i = src.find('executed')
# find archive logic
for kw in ('executed.json', 'archive', 'unlink'):
    j = src.find(kw)
    if j >= 0:
        print('KW:', kw)
        print(src[max(0,j-400):j+300])
        print('=====')
