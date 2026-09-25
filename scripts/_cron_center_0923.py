import sqlite3, os, glob
BASE = os.path.expanduser('~/.hermes/stockdb')
s = sqlite3.connect(os.path.join(BASE,'signals.db'))
# 中枢系信号近10日
for t in ['fusion_center_signals']:
    cols=[c[1] for c in s.execute(f"PRAGMA table_info({t})").fetchall()]
    print(t, cols)
    rows = s.execute(f"SELECT date, COUNT(*), MIN(rank_pct), MAX(rank_pct) FROM {t} GROUP BY date ORDER BY date DESC LIMIT 8").fetchall()
    for r in rows: print(r)
# 中枢版IC：找 ic 表里的 center 列
tabs=[r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%ic%')").fetchall()]
print('ic tables:', tabs)
for t in tabs:
    cols=[c[1] for c in s.execute(f"PRAGMA table_info({t})").fetchall()]
    if any('center' in c for c in cols):
        print(t, 'has center cols:', [c for c in cols if 'center' in c])
# ic_window center 序列
rows = s.execute("SELECT signal_date, ic_center_w10, fwd10_top_center, ic_dual_w10, fwd10_top_dual, fwd10_top_main FROM ic_window ORDER BY signal_date DESC LIMIT 12").fetchall()
for r in rows: print(r)
s.close()
# NAS 备份最近记录
import subprocess
outs = sorted(glob.glob(os.path.expanduser('~/.hermes/cron/output/*64213b771537*')))
print(outs[-3:] if outs else 'no nas output files')
if outs:
    last = sorted(outs)[-1]
    print('LAST:', last)
    print(subprocess.run(['tail','-20',last],capture_output=True,text=True).stdout)
