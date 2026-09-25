#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 第四轮：IC窗口聚合 + reg10手工复算 + NAS日志时间线 + 板块/持仓补充"""
import duckdb, sqlite3, json, os, subprocess, re
BASE = os.path.expanduser('~/.hermes/stockdb')
out = {}
sc = sqlite3.connect(os.path.join(BASE, 'signals.db'))
sig_db = os.path.join(BASE, 'signals.db')

# A) ic_window 各系 w10 均值：近8个信号日 vs 8月中
rows = sc.execute("SELECT signal_date, ic_reg10_w10, ic_reg20_w20, ic_fusion_w10, ic_center_w10, ic_dual_w10, ic_cmmr_w10, ic_cmmrf_w10, fwd10_top, fwd10_top_center, fwd10_top_dual FROM ic_window ORDER BY signal_date DESC").fetchall()
win = [r for r in rows if str(r[0]) >= '20260901']
aug = [r for r in rows if '20260810' <= str(r[0]) <= '20260831']

def m(lst, i):
    v = [r[i] for r in lst if r[i] is not None]
    return (round(sum(v)/len(v), 4), len(v)) if v else (None, 0)

out['sep_reg10_w10'] = m(win, 1)
out['aug_reg10_w10'] = m(aug, 1)
out['sep_fusion_w10'] = m(win, 3)
out['aug_fusion_w10'] = m(aug, 3)
out['sep_center_w10'] = m(win, 4)
out['aug_center_w10'] = m(aug, 4)
out['sep_dual_w10'] = m(win, 5)
out['sep_cmmr_w10'] = m(win, 6)
out['sep_cmmrf_w10'] = m(win, 7)
out['w20_avail'] = [(r[0], r[2]) for r in rows if r[2] is not None]
out['reg10_series'] = [(r[0], r[1]) for r in rows[:12]]
out['sep_detail'] = [(r[0], r[1], r[3], r[4], r[5]) for r in win]

# B) 手工复算 0910 与 0918 的 reg10 十日窗 Spearman IC（交叉验证 ic_window）
tdb = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
import statistics
def manual_ic(sig_date):
    rows = sc.execute("""SELECT stock_code, reg10 FROM signal_history
                         WHERE REPLACE(date,'-','')=? AND reg10 IS NOT NULL""", (sig_date,)).fetchall()
    codes = {}
    for c, s in rows:
        c2 = c.split('.')[0]
        codes[c2] = s
    days = [r[0] for r in tdb.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>? AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH') ORDER BY trade_date LIMIT 11", (sig_date,)).fetchall()]
    d0 = tdb.execute("SELECT trade_date FROM daily WHERE trade_date<=? ORDER BY trade_date DESC LIMIT 1", (sig_date,)).fetchone()[0]
    d10 = days[-1]
    p0 = {r[0][:6]: r[1] for r in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (d0,)).fetchall()}
    p1 = {r[0][:6]: r[1] for r in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (d10,)).fetchall()}
    pairs = [(codes[c], p1[c]/p0[c]-1) for c in codes if c in p0 and c in p1 and p0[c] > 0]
    if len(pairs) < 50: return None
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0]*len(v)
        for pos, i in enumerate(order): rk[i] = pos
        return rk
    a = rank([p[0] for p in pairs]); b = rank([p[1] for p in pairs])
    n = len(pairs)
    ma, mb = sum(a)/n, sum(b)/n
    cov = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    va = sum((x-ma)**2 for x in a) ** 0.5; vb = sum((x-mb)**2 for x in b) ** 0.5
    return round(cov/(va*vb), 4), n, d0, d10
for sd in ['20260910', '20260908', '20260824']:
    out['manual_reg10_'+sd] = manual_ic(sd)

# C) 指数与成交额细节
out['idx_recent'] = tdb.execute("""
  SELECT trade_date, ts_code, close, pct_chg FROM index_daily_raw
  WHERE ts_code IN ('000852.SH','000001.SH') AND trade_date>='20260916' ORDER BY trade_date, ts_code""").fetchall()
tdb.close()

# D) NAS 备份日志时间线
lg = os.path.expanduser('~/.hermes/logs/nas_backup.log')
try:
    lines = open(lg, errors='ignore').read().splitlines()
    hits = [(i, l) for i, l in enumerate(lines) if '===== NAS 备份' in l or '✅ NAS 备份完成' in l or '❌' in l]
    out['nas_timeline'] = hits[-14:]
except Exception as e:
    out['nas_err'] = str(e)
sc.close()
print(json.dumps(out, ensure_ascii=False, default=str, indent=1))
