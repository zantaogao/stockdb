import glob, os, time, json
# agent_auto (strategy account) — does it trade via exec_agent or its own path? check last trades
d = json.load(open('/Users/zantao/.hermes/stockdb/sim_accounts/agent_auto.json'))
print('agent_auto keys:', list(d.keys())[:10])
tr = d.get('trades', [])
print('last trades:', tr[-2:] if tr else 'none')
print('last_update fields:', {k:v for k,v in d.items() if 'date' in k.lower() or 'time' in k.lower() or 'nav' in k.lower()})
