from pathlib import Path
src = open('/Users/zantao/.hermes/stockdb/scripts/intraday_decision.py').read()
i = src.find('STATE_DB')
print(src[max(0,i-300):i+300])
