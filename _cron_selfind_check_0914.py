#!/usr/bin/env python3
"""只读核查: 双轨对比 20260911 里特征计算失败的股票性质 + 当前库新鲜度"""
import duckdb, os, sys, traceback, time
from pathlib import Path

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
print("now:", time.strftime('%Y-%m-%d %H:%M:%S'))
c = duckdb.connect(DB, read_only=True)
print("stk_factor max:", c.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0])
print("daily max:", c.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0])

fails = ['301669','301583','001248','001393','301688','001365','001689',
         '603407','688801','001257','688635','688813','601123','603293','603435']
rows = c.execute(
    "SELECT ts_code, MIN(trade_date), MAX(trade_date), COUNT(*) FROM daily "
    "WHERE ts_code IN (" + ",".join("?"*len(fails)) + ") GROUP BY ts_code ORDER BY 2",
    [f + ('.SZ' if f[0] in '03' else '.SH') for f in fails]).fetchall()
print("--- 失败标的 daily 覆盖 ---")
for r in rows:
    print(r)

# indicators.db 覆盖
ip = Path('/Users/zantao/.hermes/stockdb/indicators.db')
print("indicators.db exists:", ip.exists(), ip.stat().st_size if ip.exists() else '')
if ip.exists():
    ic = duckdb.connect(str(ip), read_only=True)
    tabs = [t[0] for t in ic.execute("SHOW TABLES").fetchall()]
    print("indicators tables:", tabs)
    for t in tabs:
        try:
            print(t, ic.execute(f"SELECT COUNT(*), MAX(trade_date) FROM {t}").fetchone())
        except Exception as e:
            print(t, "err", e)
    ic.close()

# 复现一个失败的异常
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
from core.scoring import score_stock
for code in ['301669', '001248']:
    for selfind in (False, True):
        if selfind:
            os.environ['SELF_IND'] = '1'
        else:
            os.environ.pop('SELF_IND', None)
        try:
            r = score_stock(code, conn=c, as_of_date='20260911')
            print(code, "SELF_IND=", selfind, "->", None if r is None else r.get('fusion'))
        except Exception as e:
            print(code, "SELF_IND=", selfind, "EXC:", type(e).__name__, e)
            if code == '301669':
                traceback.print_exc()
c.close()
