import duckdb, sys, json, os, subprocess

# 先清锁文件
for f in ['/Users/zantao/.hermes/stockdb/tushare.db.wal', '/Users/zantao/.hermes/stockdb/tushare.db.shm']:
    if os.path.exists(f):
        try: os.remove(f)
        except: pass

# 用hermes的uv python（有duckdb）
py_path = '/Users/zantao/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none/bin/python'
if not os.path.exists(py_path):
    py_path = '/usr/local/bin/python3'

script = '''
import duckdb, sys, json, os
for f in ["/Users/zantao/.hermes/stockdb/tushare.db.wal", "/Users/zantao/.hermes/stockdb/tushare.db.shm"]:
    if os.path.exists(f):
        try: os.remove(f)
        except: pass

conn = db.get_tushare_db()

# 今天所有signal_history记录（不限打板，全查）
results = conn.execute("""
    SELECT date, type, code, name, score, time
    FROM signal_history 
    WHERE date >= '20260710' 
    ORDER BY time DESC 
    LIMIT 50
""").fetchall()

if not results:
    print("NO_SIGNALS")
else:
    for r in results[:30]:
        obj = {"date": str(r[0]), "time": str(r[5])[:19] if r[5] else "", 
               "type": str(r[1]), "code": r[2], "name": r[3], "score": r[4]}
        print(json.dumps(obj, ensure_ascii=False))

conn.close()
'''

r = subprocess.run([py_path, '-c', script], capture_output=True, text=True)
if r.returncode == 0:
    for line in r.stdout.strip().split('\n'):
        if not line or 'NO_SIGNALS' in line:
            continue
        try:
            obj = json.loads(line)
            print(f"  {obj['time']} | type={obj['type']:<15} | score={obj['score']:>5} | code={obj['code']} | name={obj['name']}")
        except:
            print(f"  RAW: {line}")
else:
    print(f"ERR: {r.stderr[:500]}")
