import sqlite3, duckdb, os, statistics
H = os.path.expanduser('~/.hermes/stockdb')
s = sqlite3.connect(f'{H}/signals.db')
tabs = [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print([x for x in tabs if 'center' in x or 'fusion' in x])

# 1. ic_daily 近8信号日 各腿均值/趋势
rows = s.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40, top_ret, bottom_ret FROM ic_daily ORDER BY signal_date DESC LIMIT 8").fetchall()
print('== ic_daily 最近→最早 ==')
for r in rows: print('  ', r[0], 'fusion', round(r[1],3), 'reg10', round(r[2],3), 'reg20', round(r[3],3), 'reg40', round(r[4],3), 'top10超额', round(r[5],2))
d = list(reversed(rows))
for i,leg in [(1,'fusion'),(2,'reg10'),(3,'reg20'),(4,'reg40')]:
    last5 = [r[i] for r in d[-5:]]; prev3 = [r[i] for r in d[:-5]]
    print(f'{leg}: 近5均 {statistics.mean(last5):+.3f} 前3均 {statistics.mean(prev3):+.3f}' if prev3 else f'{leg}: 近5均 {statistics.mean(last5):+.3f}')
t5 = [r[5] for r in d[-5:]]
print('top10次日超额 近5均', round(statistics.mean(t5),2), '正天数', sum(1 for x in t5 if x>0), '/5')

# 2. center_dual 近5
rows = s.execute("SELECT date, ic, top_ret, bottom_ret FROM center_dual_ic_daily ORDER BY date DESC LIMIT 8").fetchall()
print('== center_dual_ic_daily ==')
for r in rows: print('  ', r)
d = list(reversed(rows))
print('组合IC 近5均', round(statistics.mean([r[1] for r in d[-5:]]),3), 'top10超额近5均', round(statistics.mean([r[2] for r in d[-5:]]),2))

# 3. 中枢版榜单 top10 次日超额: 找 fusion_center 相关表
for tb in tabs:
    if 'center' in tb:
        cols = [x[1] for x in s.execute(f"PRAGMA table_info({tb})")]
        print(tb, cols[:12])
