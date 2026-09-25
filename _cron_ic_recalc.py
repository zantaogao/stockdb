#!/usr/bin/env python3
"""IC 页面审查: model_ic + cmmr_ic + fusion_ic 独立复算 2026-08-08
不复刻被测代码, 独立读取评分+收益重新计算"""
import sqlite3, duckdb
import numpy as np
from scipy.stats import spearmanr

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'

s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

tds = [r[0] for r in t.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]

def code_to_ts(c):
    return f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ"

def pearson(a, b):
    if len(a) != len(b) or len(a) < 10:
        return None
    return float(np.corrcoef(np.array(a, dtype=float), np.array(b, dtype=float))[0, 1])

def next_td(d):
    i = tds.index(d)
    return tds[i + 1] if i + 1 < len(tds) else None

print("=" * 70)
print("1) model_ic 复算（ic_daily 4 行, Pearson 次日IC）")
rows = s.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40, sample_size FROM ic_daily ORDER BY signal_date").fetchall()
for sd, ifu, ir10, ir20, ir40, ss in rows:
    sd8 = str(sd).replace('-', '')
    nt = next_td(sd8)
    if not nt:
        print(f"  {sd}: 无次日, 跳过")
        continue
    # 评分
    sig = s.execute("SELECT stock_code, fusion_score, reg10, reg20, reg40 FROM signal_history WHERE REPLACE(date,'-','')=?", (sd8,)).fetchall()
    px = {}
    for d in (sd8, nt):
        for tc, cl in t.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (d,)).fetchall():
            px[(d, tc)] = float(cl)
    f, r10, r20, r40, ret = [], [], [], [], []
    for code, fus, a, b, c4 in sig:
        tc = code_to_ts(code)
        p0, pn = px.get((sd8, tc)), px.get((nt, tc))
        if not p0 or p0 <= 0 or not pn or pn <= 0:
            continue
        ret.append((pn / p0 - 1) * 100)
        f.append(float(fus) if fus is not None else 0.0)
        r10.append(float(a) if a is not None else 0.0)
        r20.append(float(b) if b is not None else 0.0)
        r40.append(float(c4) if c4 is not None else 0.0)
    cf, c10, c20, c40 = pearson(f, ret), pearson(r10, ret), pearson(r20, ret), pearson(r40, ret)
    match = "✓" if (cf is not None and abs(cf - ifu) < 0.005) else "✗ 不一致"
    print(f"  {sd}: 表值 fusion={ifu} reg10={ir10} reg20={ir20} reg40={ir40} n={ss}")
    print(f"         复算 fusion={cf:.4f} reg10={c10:.4f} reg20={c20:.4f} reg40={c40:.4f} n={len(ret)} {match}")

print("=" * 70)
print("2) cmmr_ic / fusion_ic 复算（Spearman, 注意 forward_days 窗口）")
for tb, col in (('cmmr_ic_daily', 'cmmr_score'), ('fusion_ic_daily', 'fusion_score_cmmr')):
    print(f"\n  [{tb}] (列: {[c[1] for c in s.execute(f'PRAGMA table_info({tb})').fetchall()]})")
    rows = s.execute(f"SELECT * FROM {tb} ORDER BY date").fetchall()
    cols = [c[1] for c in s.execute(f"PRAGMA table_info({tb})").fetchall()]
    for r in rows:
        d = dict(zip(cols, r))
        sd8 = str(d['date']).replace('-', '')
        nt = next_td(sd8)
        if not nt:
            print(f"  {sd8}: 无次日")
            continue
        sig = s.execute(f"SELECT stock_code, {col} FROM signal_history WHERE REPLACE(date,'-','')=? AND {col} IS NOT NULL", (sd8,)).fetchall()
        px = {}
        for dd in (sd8, nt):
            for tc, cl in t.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (dd,)).fetchall():
                px[(dd, tc)] = float(cl)
        sc, ret = [], []
        for code, scv in sig:
            tc = code_to_ts(code)
            p0, pn = px.get((sd8, tc)), px.get((nt, tc))
            if not p0 or p0 <= 0 or not pn or pn <= 0:
                continue
            sc.append(float(scv))
            ret.append((pn / p0 - 1) * 100)
        ic = float(spearmanr(sc, ret).statistic) if len(sc) >= 10 and len(set(sc)) > 1 else None
        fwd = d.get('forward_days')
        win = d.get('win_rate')
        match = "✓" if ic is not None and abs(ic - float(d['ic'])) < 0.005 else "✗"
        print(f"  {sd8}: 表值 ic={d['ic']} fwd_days={fwd} win={win} → 复算 ic={ic:.4f} n={len(sc)} {match}")

print("=" * 70)
print("3) 7/30 信号复制检测（signal_history 7/30 vs 7/29 相同率）")
for d1, d2 in (('20260730', '20260729'), ('20260731', '20260730'), ('20260803', '20260731')):
    q1 = {r[0]: (r[1], r[2], r[3]) for r in s.execute("SELECT stock_code, reg10, reg20, reg40 FROM signal_history WHERE REPLACE(date,'-','')=?", (d1,)).fetchall()}
    q2 = {r[0]: (r[1], r[2], r[3]) for r in s.execute("SELECT stock_code, reg10, reg20, reg40 FROM signal_history WHERE REPLACE(date,'-','')=?", (d2,)).fetchall()}
    common = set(q1) & set(q2)
    if common:
        same = sum(1 for c in common if q1[c] == q2[c])
        print(f"  {d1} vs {d2}: 共同 {len(common)}, 三模型分完全相同 {same} ({same/len(common)*100:.1f}%)")

s.close(); t.close()
