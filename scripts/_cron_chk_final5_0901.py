# Final state check before writing report
import sqlite3, subprocess

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('signal_history latest:', sig.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone())
print('new_factors latest:', sig.execute("SELECT MAX(date) FROM new_factors").fetchone())
print('fusion_3f latest:', sig.execute("SELECT MAX(date) FROM fusion_3f_signals").fetchone())
print('fusion_center latest:', sig.execute("SELECT MAX(date) FROM fusion_center_signals").fetchone())

r = subprocess.run(['ps', '-ax', '-o', 'pid,etime,command'], capture_output=True, text=True)
mine = [l[:120] for l in r.stdout.splitlines() if 'stockdb' in l and 'grep' not in l]
print('stockdb-related procs:'); [print(' ', m) for m in mine[:10]]