import importlib.util, sys, datetime
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
spec = importlib.util.spec_from_file_location('ia', '/Users/zantao/.hermes/stockdb/agents/exec_agent.py')
# just read the trading-window logic without running main
src = open('/Users/zantao/.hermes/stockdb/agents/exec_agent.py').read()
i = src.find('非交易时段')
print(src[max(0,i-900):i+200])
