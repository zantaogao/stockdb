import duckdb, os, glob
BASE = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
# 688217 睿昂基因日线
for code in ['688217.SH']:
    rows = t.execute("SELECT trade_date,open,high,low,close,pct_chg,vol FROM daily WHERE ts_code=? AND trade_date>='20260820' ORDER BY trade_date", [code]).fetchall()
    print(code, "N=", len(rows))
    for r in rows[-14:]: print(r)
# 600363 是否有0929数据（停牌?）
print("600363 last rows:")
for r in t.execute("SELECT trade_date,close,pct_chg FROM daily WHERE ts_code='600363.SH' ORDER BY trade_date DESC LIMIT 3").fetchall():
    print(r)
# 000428华天酒店 000430 等涨停统计近5日 for CMMR榜
# NAS backup logs
import subprocess
for p in glob.glob(os.path.expanduser('~/.hermes/cron/output/*64213b771537*')):
    print("CRONOUT:", p)
for p in sorted(glob.glob(os.path.expanduser('~/.hermes/stockdb/logs/*nas*'))) + sorted(glob.glob(os.path.expanduser('~/.hermes/logs/*nas*'))):
    print("LOG:", p)
