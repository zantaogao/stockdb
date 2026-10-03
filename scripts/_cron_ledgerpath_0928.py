from pathlib import Path
import glob, os, time
src = open('/Users/zantao/.hermes/stockdb/scripts/intraday_decision.py').read()
for kw in ('ca_run_log', 'ca_calendar', 'ledger'):
    j = src.find(kw)
    print(kw, '->', j)
# ledger path resolution
i = src.find('def _db_conn')
print(src[i:i+800] if i>=0 else 'no _db_conn def')
