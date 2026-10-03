#!/usr/bin/env python3
# 10-01 IC 监控异常核查：哨兵IC近12日走势 + 真窗口IC + 市场环境
import sqlite3, os, sys

home = os.path.expanduser('~/.hermes')
state_db = os.path.join(home, 'stockdb', 'signals.db')
print('state_db =', state_db)
conn = sqlite3.connect(f'file:{state_db}?mode=ro', uri=True)
cur = conn.cursor()

print('\n=== ic_daily 近12日哨兵IC (signal_date, fusion, reg10, reg20, reg40) ===')
for r in cur.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 12"):
    print(r)

print('\n=== factor_ic_roll 融合/三因子行最新 ===')
try:
    for r in cur.execute("SELECT factor_name, as_of_date, ic_mean, icir, win_rate, n_days FROM factor_ic_roll WHERE factor_name LIKE '%fusion%' OR factor_name LIKE '%3f%' OR factor_name LIKE '%强买%' ORDER BY as_of_date DESC LIMIT 8"):
        print(r)
except Exception as e:
    print('ERR', e)

print('\n=== cmmr_ic_daily 近6行 ===')
for r in cur.execute("SELECT date, ic, samples, forward_days FROM cmmr_ic_daily ORDER BY date DESC LIMIT 6"):
    print(r)

print('\n=== fusion_ic_daily 近6行 ===')
for r in cur.execute("SELECT date, ic, samples, forward_days FROM fusion_ic_daily ORDER BY date DESC LIMIT 6"):
    print(r)

print('\n=== etf_ic 近3行 ===')
for r in cur.execute("SELECT signal_date, ic_etf, ic_spearman, sample_size FROM etf_ic ORDER BY signal_date DESC LIMIT 3"):
    print(r)

print('\n=== ic_window 近12行 (sd, reg10w10, fusionw10, fusionw20, 3fw10, cmmrw10, cmmrfw10, centerw10, dualw10, fwd10top) ===')
cols = None
try:
    cols = [c[1] for c in cur.execute("PRAGMA table_info(ic_window)")]
    print('cols:', cols)
    q = ("SELECT signal_date, ic_reg10_w10, ic_fusion_w10, ic_fusion_w20, ic_3f_w10, "
         "ic_cmmr_w10, ic_cmmrf_w10, ic_center_w10, ic_dual_w10, fwd10_top "
         "FROM ic_window ORDER BY signal_date DESC LIMIT 12")
    for r in cur.execute(q):
        print(r)
except Exception as e:
    print('ERR', e)

conn.close()

# 市场环境：0929/0930 全市场宽度（分化 vs 普涨/普跌）
print('\n=== 市场环境 (tushare.daily) ===')
try:
    import duckdb
    ts = os.path.join(home, 'stockdb', 'tushare.db')
    if not os.path.exists(ts):
        ts = os.path.join(home, 'tushare.db')
    tc = duckdb.connect(ts, read_only=True)
    for d in ('20260928', '20260929', '20260930'):
        row = tc.execute(f"""
            SELECT AVG(pct_chg), SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END)*1.0/COUNT(*), COUNT(*)
            FROM daily WHERE trade_date='{d}'
        """).fetchone()
        print(d, 'mean_pct_chg=%.2f' % row[0], 'up_ratio=%.1f%%' % (row[1]*100), 'n=%d' % row[2])
    tc.close()
except Exception as e:
    print('ERR market', e)
