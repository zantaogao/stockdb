import re
src = open('/Users/zantao/.hermes/stockdb/agents/exec_agent.py').read()
# find where EXECUTED orders are recorded: trade_log / execution_logs inserts
for pat in ('trade_log', 'execution_logs', 'executed'):
    for m in re.finditer(pat, src):
        line_no = src[:m.start()].count('\n')+1
        pass
# simpler: print lines mentioning INSERT
for i,l in enumerate(src.splitlines(),1):
    if 'INSERT' in l or 'order_id' in l or 'exec_id' in l:
        print(i, l.strip()[:160])
