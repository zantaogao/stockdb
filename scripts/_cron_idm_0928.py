from pathlib import Path
src = open('/Users/zantao/.hermes/stockdb/scripts/intraday_decision.py').read()
i = src.find('def main')
print(src[i:i+2600])
