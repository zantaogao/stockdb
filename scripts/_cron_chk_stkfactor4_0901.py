import json, glob, os

# 1) was there an output file written this run?
files = sorted(glob.glob('/Users/zantao/.hermes/cron/output/099aee371ab5/*.md'))
print('output files latest 3:', [os.path.basename(f) for f in files[-3:]])

# 2) check state.db / ledger for this session's messages
import sqlite3
for dbp in ['/Users/zantao/.hermes/state.db', '/Users/zantao/.hermes/agent_state.db', '/Users/zantao/.hermes/session.db']:
    if os.path.exists(dbp):
        print('DB:', dbp)

# 3) look at the previous run's output tail for comparison of format
if files:
    prev = files[-2] if len(files) > 1 else files[-1]
    print('=== prev run tail:', prev)
    print(open(prev, encoding='utf-8', errors='replace').read()[-800:])