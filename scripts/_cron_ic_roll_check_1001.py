import sqlite3, os, statistics
home = os.path.expanduser('~/.hermes')
conn = sqlite3.connect(f'file:{home}/stockdb/signals.db?mode=ro', uri=True)
cur = conn.cursor()

rows = cur.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()
rows = rows[::-1]
print('哨兵IC 近20信号日滚动均值 (n=%d, %s ~ %s):' % (len(rows), rows[0][0], rows[-1][0]))
for i, name in [(1,'fusion'), (2,'reg10'), (3,'reg20'), (4,'reg40')]:
    vals = [r[i] for r in rows if r[i] is not None]
    pos = sum(1 for v in vals if v > 0)
    print('  %-7s mean=%+.4f  正天数=%d/%d  最新=%s' % (name, statistics.mean(vals), pos, len(vals), rows[-1][i]))

# 前半/后半（近20日拆两半看趋势）
for i, name in [(1,'fusion'), (2,'reg10'), (3,'reg20'), (4,'reg40')]:
    vals = [r[i] for r in rows if r[i] is not None]
    half = len(vals)//2
    print('  %-7s 前10日均=%+.4f  后10日均=%+.4f' % (name, statistics.mean(vals[:half]), statistics.mean(vals[half:])))

# ic_window 真窗口近10行汇总
print('\nic_window 真窗口近10信号日均值:')
wrows = cur.execute("""SELECT signal_date, ic_reg10_w10, ic_fusion_w10, ic_3f_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_center_w10, ic_dual_w10, fwd10_top FROM ic_window ORDER BY signal_date DESC LIMIT 10""").fetchall()[::-1]
print('  范围:', wrows[0][0], '~', wrows[-1][0])
for i, name in [(1,'reg10w10'),(2,'fusionw10'),(3,'3fw10'),(4,'cmmrw10'),(5,'cmmrfw10'),(6,'centerw10'),(7,'dualw10'),(8,'fwd10top')]:
    vals = [r[i] for r in wrows if r[i] is not None]
    if vals:
        print('  %-10s mean=%+.4f  正=%d/%d' % (name, statistics.mean(vals), sum(1 for v in vals if v>0), len(vals)))

# 波动组 nan 排查
print('\n波动组 factor_group_ic_daily 近6行:')
for r in cur.execute("SELECT * FROM factor_group_ic_daily WHERE factor_group LIKE '%波动%' ORDER BY 1 DESC LIMIT 6").fetchall():
    print(' ', r)
cols = [c[1] for c in cur.execute("PRAGMA table_info(factor_group_ic_daily)")]
print(' cols:', cols)
conn.close()
