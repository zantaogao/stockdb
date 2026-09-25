import sqlite3, statistics
c = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
rows = c.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()
cols = {'fusion':[], 'reg10':[], 'reg20':[], 'reg40':[]}
for r in rows:
    cols['fusion'].append(r[1]); cols['reg10'].append(r[2]); cols['reg20'].append(r[3]); cols['reg40'].append(r[4])
print('=== ic_daily 20日滚动(哨兵口径) ===')
for k,v in cols.items():
    v2=[x for x in v if x is not None]
    if v2:
        print(k, 'n=',len(v2), 'mean=', round(statistics.mean(v2),4), 'std=', round(statistics.pstdev(v2),4),
              'pos=', sum(1 for x in v2 if x>0),'/',len(v2), 'latest=', v[0])
print('--- 最近5信号日:')
for r in rows[:5]: print(r)
print('--- ic_window 最新3行(真窗口):')
for r in c.execute("SELECT signal_date, ic_reg10_w10, ic_reg20_w20, ic_fusion_w10, ic_fusion_w20, ic_3f_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_center_w10, ic_dual_w10 FROM ic_window ORDER BY signal_date DESC LIMIT 3"): print(r)
print('--- factor_ic_roll:')
try:
    for r in c.execute("SELECT factor_name, mean_ic, n_days, win_rate FROM factor_ic_roll ORDER BY factor_name"): print(r)
except Exception as e: print('err', e)
