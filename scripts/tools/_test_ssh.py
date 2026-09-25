import subprocess, sys
from pathlib import Path

PC_SCRIPT = r'''
import sqlite3, json, sys
DB = r'C:\Users\zanta\tdx_stock_data.db'
c = sqlite3.connect(DB).cursor()
mode = sys.argv[1]
if mode == 'latest':
    c.execute('SELECT MAX(date) FROM daily')
    r = c.fetchone()[0]
    print(r) if r else None
c.close()
'''

script_path = str(Path.cwd() / '_tdx_query.py')
with open(script_path, 'w') as f:
    f.write(PC_SCRIPT)

# Test SCP
r1 = subprocess.run(
    ['scp', script_path, 'pumma@192.168.3.168:C:/temp/tdx_query.py'],
    capture_output=True, text=True, timeout=30
)
print('SCP return:', r1.returncode)
print('SCP stderr:', r1.stderr[:200] if r1.stderr else '')

# Test SSH exec
r2 = subprocess.run(
    ['ssh', 'pumma@192.168.3.168', 'cmd /c', 'python C:/temp/tdx_query.py latest'],
    capture_output=True, text=True, timeout=30
)
print('SSH return:', r2.returncode)
print('SSH stdout:', repr(r2.stdout[:200]))
print('SSH stderr:', repr(r2.stderr[:200]))

Path(script_path).unlink(missing_ok=True)
