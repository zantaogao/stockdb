import sqlite3, os, time, glob
BASE = '/Users/zantao/.hermes/stockdb'
c = sqlite3.connect(BASE + '/ledger.db', timeout=10)
print("holdings status:", c.execute("SELECT status, COUNT(*) FROM holdings GROUP BY status").fetchall())
print("最新 update_time:", c.execute("SELECT MAX(update_time) FROM holdings").fetchone()[0])
c.close()

# 备份目录里 tushare 备份文件情况
for d in [os.path.expanduser('~/.hermes/stockdb/db_backups'), os.path.expanduser('~/db_backups')]:
    if os.path.isdir(d):
        fs = sorted(glob.glob(d + '/*'), key=os.path.getmtime)[-12:]
        print("\n==", d)
        for f in fs:
            print(" ", time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))), f"{os.path.getsize(f)/1e6:.0f}MB", os.path.basename(f))

# backup.sh 最近日志
for lg in sorted(glob.glob(BASE + '/logs/*backup*'), key=os.path.getmtime)[-3:]:
    st = os.stat(lg)
    print("\nlog:", lg, time.strftime('%m-%d %H:%M', time.localtime(st.st_mtime)))
    print(open(lg, errors='ignore').read()[-1200:])
