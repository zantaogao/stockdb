from pathlib import Path
src = Path('/Users/zantao/.hermes/scripts/exec_agent.sh').read_text()
print(repr(src))
import subprocess
# check core/trading_time mtime and git state of stockdb exec scripts
import os, time
for f in ('/Users/zantao/.hermes/stockdb/core/trading_time.py',
          '/Users/zantao/.hermes/stockdb/agents/exec_agent.py',
          '/Users/zantao/.hermes/scripts/exec_agent.sh',
          '/Users/zantao/.hermes/stockdb/scripts/intraday_decision.py'):
    print(time.strftime('%y-%m-%d %H:%M', time.localtime(os.path.getmtime(f))), f)
