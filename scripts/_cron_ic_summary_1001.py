import sqlite3, os, statistics
home = os.path.expanduser('~/.hermes')
conn = sqlite3.connect(f'file:{home}/stockdb/signals.db?mode=ro', uri=True)

print('=== ic_daily 近20信号日（哨兵IC滚动）===')
rows = conn.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()[::-1]
if rows:
    print('范围: %s ~ %s (n=%d)' % (rows[-1][0], rows[0][0], len(rows)))
    for i, name in [(1,'fusion'),(2,'reg10'),(3,'reg20'),(4,'reg40')]:
        vals=[r[i] for r in rows if r[i] is not None]
        if not vals:
            print('%-8s 全None' % name); continue
        r10=[r[i] for r in rows[-10:] if r[i] is not None]
        latest = rows[-1][i]
        print('%-8s 20日均=%+.4f 近10日均=%+.4f 最新(%s)=%s 正=%d/%d' % (
            name, statistics.mean(vals), statistics.mean(r10), rows[-1][0],
            ('%+.4f'%latest) if latest is not None else 'None',
            sum(1 for v in vals if v>0), len(vals)))
    print('末5行:', rows[-5:])

print()
print('=== ic_window 列名 ===')
cols=[c[1] for c in conn.execute("PRAGMA table_info(ic_window)")]
print(cols)
wrows=conn.execute("SELECT * FROM ic_window ORDER BY signal_date DESC LIMIT 10").fetchall()[::-1]
di=cols.index('signal_date')
for c in cols:
    if c=='signal_date': continue
    ci=cols.index(c)
    vals=[r[ci] for r in wrows if isinstance(r[ci],(int,float))]
    if vals:
        print('  %-18s 近10日均=%+.4f 正=%d/%d 最新=%s' % (c, statistics.mean(vals), sum(1 for v in vals if v>0), len(vals), wrows[-1][ci]))

print()
print('=== factor_group_ic_daily 波动组（nan排查）===')
fcols=[c[1] for c in conn.execute("PRAGMA table_info(factor_group_ic_daily)")]
print('cols:', fcols)
namec=next((c for c in fcols if c in ('factor_group','group_name','factor_name','name')), None)
datec=next((c for c in fcols if 'date' in c.lower()), fcols[0])
icc=next((c for c in fcols if 'ic' in c.lower()), None)
if namec:
    q=f"SELECT {datec}, {namec}, {icc} FROM factor_group_ic_daily WHERE {namec} LIKE '%波动%' ORDER BY {datec} DESC LIMIT 10"
    for r in conn.execute(q): print(' ', r)

print()
print('=== cmmr / fusion / center_dual 最新3行 ===')
for t in ('cmmr_ic_daily','fusion_ic_daily','center_dual_ic_daily'):
    tc=[c[1] for c in conn.execute(f"PRAGMA table_info({t})")]
    d=next((c for c in tc if 'date' in c.lower()), tc[0])
    try:
        rr=conn.execute(f"SELECT * FROM {t} ORDER BY {d} DESC LIMIT 3").fetchall()
        print(t, 'cols=', tc)
        for r in rr: print('  ', r)
    except Exception as e:
        print(t, 'ERR', e)
conn.close()

# 市场环境
try:
    import duckdb
    tc=duckdb.connect(f'{home}/stockdb/tushare.db', read_only=True)
    print()
    print('=== 市场环境 daily 近12交易日 ===')
    for r in tc.execute("""
        SELECT trade_date, ROUND(AVG(pct_chg),3),
               ROUND(SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END)*100.0/COUNT(*),1), COUNT(*)
        FROM daily WHERE trade_date>='20260915' GROUP BY trade_date ORDER BY trade_date
    """).fetchall(): print(' ', r)
    tc.close()
except Exception as e:
    print('市场数据 ERR:', e)
