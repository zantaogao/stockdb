from pathlib import Path
import glob, os, time
src = open('/Users/zantao/.hermes/stockdb/agents/exec_agent.py').read()
i = src.find('executed_file')
j = src.find('executed.json')
k = src.find('def write_execution_report')
if k < 0:
    # find any function that writes executed.json
    idxs = [m for m in range(len(src)) if src.startswith('executed.json', m)]
    for m in idxs[:5]:
        print('at line', src[:m].count(chr(10))+1)
        print(src[max(0,m-500):m+200])
        print('-----')
