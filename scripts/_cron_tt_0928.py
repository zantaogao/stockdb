from pathlib import Path
import importlib.util, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
src = open('/Users/zantao/.hermes/stockdb/core/trading_time.py').read()
print(src[:2500])
