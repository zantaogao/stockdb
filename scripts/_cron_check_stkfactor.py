import sqlite3, duckdb, glob, os, time

# 1) stk_factor 尾部（tushare.db 只读）
c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for t in ['stk_factor', 'daily']:
    try:
        print(t, 'MAX trade_date =', c.execute(f'SELECT MAX(trade_date), COUNT(*) FROM {t}').fetchone())
    except Exception as e:
        print(t, 'ERR', str(e)[:120])

# 2) signals.db 三表最新日
s = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db', timeout=30)
for t in ['new_factors', 'flow_alpha', 'vol_adj', 'fusion_3f_signals', 'fusion_center_signals']:
    try:
        print(t, 'MAX date =', s.execute(f"SELECT MAX(REPLACE(date,'-','')), COUNT(*) FROM {t}").fetchone())
    except Exception as e:
        print(t, 'ERR', str(e)[:120])

# 3) 本 cron 近8次运行输出里是否已有 PYTHONPATH 症状
d = os.path.expanduser('~/.hermes/cron/output/099aee371ab5')
files = sorted(glob.glob(d + '/*.md'))[-8:]
for f in files:
    txt = open(f, errors='ignore').read()
    bad = ('unsupported operand' in txt) or ('Version mismatch' in txt) or ('backfill_stk_factor.py 失败' in txt)
    print(os.path.basename(f), 'POLLUTED' if bad else 'clean', len(txt))
