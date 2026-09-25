import sqlite3, duckdb
today = '20260918'
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=10)
hold = [x[0] for x in c.execute("SELECT code FROM holdings WHERE status='holding'").fetchall()]
print("持仓只数:", len(hold))
c.close()
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
try:
    cols = [r[1] for r in d.execute("DESCRIBE dividend").fetchall()]
    print("dividend cols:", cols)
    ex = d.execute(f"SELECT ts_code, ex_date FROM dividend WHERE REPLACE(ex_date,'-','')='{today}'").fetchall()
    hs = {h.split('.')[0] for h in hold}
    print("今日除权除息全市场:", len(ex), "| 命中持仓:", [x for x in ex if x[0].split('.')[0] in hs])
except Exception as e:
    print("dividend err:", e)
d.close()

# 检查今日 cron 里 ca 任务的实际运行日志
import glob, os, time
for lg in sorted(glob.glob('/Users/zantao/.hermes/stockdb/logs/*ca*'), key=os.path.getmtime)[-5:]:
    st = os.stat(lg)
    print("log:", lg, time.strftime('%m-%d %H:%M', time.localtime(st.st_mtime)), st.st_size)
    if time.strftime('%Y-%m-%d', time.localtime(st.st_mtime)) == '2026-09-18':
        print("  ---tail---")
        print(open(lg, errors='ignore').read()[-1500:])
