# -*- coding: utf-8 -*-
"""IC 序列 + 备份链（2026-09-15 盘后，只读）"""
import sqlite3, os, subprocess, glob, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sc = sqlite3.connect(os.path.join(BASE, 'signals.db'))

print("== ic_daily 近12个信号日 ==")
print("signal_date  n   ic_reg10  ic_reg20  ic_reg40  ic_fusion  ic_final  top_ret  bottom_ret  fwd10 fwd20 fwd40")
for r in sc.execute("""SELECT signal_date, sample_size, ic_reg10, ic_reg20, ic_reg40, ic_fusion, ic_final,
                              top_ret, bottom_ret, fwd10, fwd20, fwd40 FROM ic_daily
                       ORDER BY REPLACE(signal_date,'-','') DESC LIMIT 12""").fetchall():
    print("  ", tuple((round(x, 4) if isinstance(x, float) else x) for x in r))

print("\n== fusion_ic_daily 近12 ==")
for r in sc.execute("SELECT * FROM fusion_ic_daily ORDER BY REPLACE(date,'-','') DESC LIMIT 12").fetchall():
    print("  ", tuple((round(x, 4) if isinstance(x, float) else x) for x in r))

print("\n== center_dual_ic_daily 近12 ==")
for r in sc.execute("SELECT * FROM center_dual_ic_daily ORDER BY REPLACE(date,'-','') DESC LIMIT 12").fetchall():
    print("  ", tuple((round(x, 4) if isinstance(x, float) else x) for x in r))

print("\n== ic_window 近10 ==")
cols = [c[1] for c in sc.execute("PRAGMA table_info(ic_window)").fetchall()]
keep = ['signal_date', 'n', 'ic_reg10_w10', 'ic_reg20_w20', 'ic_reg40_w40', 'ic_fusion_w10', 'ic_fusion_w20',
        'ic_fusion_w40', 'fwd10_top', 'fwd20_top', 'fwd40_top', 'ic_center_w10', 'fwd10_top_center',
        'ic_dual_w10', 'fwd10_top_dual', 'fwd10_top_main', 'fwd20_top_main', 'fwd40_top_main']
for r in sc.execute("SELECT * FROM ic_window ORDER BY REPLACE(signal_date,'-','') DESC LIMIT 10").fetchall():
    dd = dict(zip(cols, r))
    print("  " + " ".join(f"{k}={round(dd[k],4) if isinstance(dd[k], float) else dd[k]}" for k in keep if k in dd))
sc.close()

print("\n== 本机备份 db_backups 最新 6 ==")
bdir = os.path.join(BASE, 'db_backups')
try:
    items = sorted(glob.glob(os.path.join(bdir, '*')), key=os.path.getmtime, reverse=True)[:6]
    for p in items:
        st = os.stat(p)
        print("  ", datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
              os.path.basename(p), f"{st.st_size/1e6:.1f}MB" if os.path.isfile(p) else os.path.getsize(p))
    if items and os.path.isdir(items[0]):
        for f in sorted(os.listdir(items[0]))[:20]:
            fp = os.path.join(items[0], f)
            print("      ", f, f"{os.path.getsize(fp)/1e6:.1f}MB" if os.path.isfile(fp) else '<dir>')
except Exception as e:
    print("  读取失败:", e)
