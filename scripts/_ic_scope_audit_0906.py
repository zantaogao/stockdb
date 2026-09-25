#!/usr/bin/env python3
"""审计：每个信号源的面板IC列（全截面） vs 执行子集IC vs Top10，是否都口径错位。
信号源与执行口径（与 ic_window.py top10_ret 一致）：
  fusion(主账户): 全分排序，无过滤
  fusion_3f:     signal='强买' 集合内排序
  cmmr:          score>0 过滤
  cmmrf:         score>0 再取p85以上
  center:        signal='强买' 集合内排序
  dual:          rank等权组合分，无过滤
成熟20d窗口 = 信号日终点日已到期的（动态取全部可算日）。"""
import sqlite3
import duckdb
import numpy as np
from scipy.stats import spearmanr

st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

tdays = [str(r[0]) for r in td.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
tidx = {d: i for i, d in enumerate(tdays)}

sig_dates = [str(r[0]) for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
mature = [d for d in sig_dates if d in tidx and tidx[d] + 20 < len(tdays)]
print('成熟20d窗口信号日:', len(mature), mature[0] if mature else '', '~', mature[-1] if mature else '')

def code_to_ts(c):
    return c + ('.SH' if c.startswith(('6', '9')) else '.SZ')

# ST/北交所过滤（与ic_window bad_codes同口径：先查它怎么定的）
bad = set()
for r in st.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    sc, nm, mk = r
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(sc)

sources = ['fusion', 'f3f', 'cmmr', 'cmmrf', 'center', 'dual']
acc = {s: {'ic_all': [], 'ic_sub': [], 'top10': [], 'mkt': [], 'n_sub': []} for s in sources}

for sd in mature:
    end = tdays[tidx[sd] + 20]
    sig = st.execute(
        "SELECT stock_code, fusion_score, cmmr_score, fusion_score_cmmr FROM signal_history "
        "WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    f3_rows = st.execute(
        "SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals "
        "WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    ct_rows = st.execute(
        "SELECT stock_code, score, signal FROM fusion_center_signals "
        "WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    f3 = {r[0]: (float(r[1]) if r[1] is not None else 0.0) for r in f3_rows}
    f3_strong = {r[0] for r in f3_rows if r[2] == '强买'}
    ct = {r[0]: (float(r[1]) if r[1] is not None else 0.0) for r in ct_rows}
    ct_strong = {r[0] for r in ct_rows if r[2] == '强买'}

    codes = [code_to_ts(r[0]) for r in sig]
    p0 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (sd,)).fetchall()}
    p1 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (end,)).fetchall()}

    recs = {s: [] for s in sources}
    ret = []
    codes_ok = []
    for row, tc in zip(sig, codes):
        code, fus, cmmr, cmmrf = row[0], row[1], row[2], row[3]
        if not p0.get(tc) or p0[tc] <= 0 or not p1.get(tc) or p1[tc] <= 0:
            continue
        if code in bad:
            continue
        n = None
        # dual 需要 n：先收集后算
        recs['fusion'].append(float(fus) if fus is not None else 0.0)
        recs['cmmr'].append(float(cmmr) if cmmr is not None else 0.0)
        recs['cmmrf'].append(float(cmmrf) if cmmrf is not None else 0.0)
        recs['f3f'].append(f3.get(code, 0.0))
        recs['center'].append(ct.get(code, 0.0))
        ret.append(p1[tc] / p0[tc] - 1)
        codes_ok.append(code)
    m = len(ret)
    if m < 100:
        continue
    n_arr = m
    # dual: rank等权
    fr = np.argsort(np.argsort(np.array(recs['f3f']))) + 1
    mr = np.argsort(np.argsort(np.array(recs['fusion']))) + 1
    recs['dual'] = list(0.5 * fr / n_arr * 100 + 0.5 * mr / n_arr * 100)
    ret = np.array(ret)
    mkt = float(ret.mean() * 100)

    strong_mask = np.array([c in f3_strong for c in codes_ok])
    cmmr_pos = np.array(recs['cmmr']) > 0
    cmmrf_pos = np.array(recs['cmmrf']) > 0
    ct_strong_mask = np.array([c in ct_strong for c in codes_ok])

    # cmmrf p85
    cf_pos_vals = np.array(recs['cmmrf'])[cmmrf_pos]
    p85 = np.quantile(cf_pos_vals, 0.85) if len(cf_pos_vals) > 10 else None
    cmmrf_mask = cmmrf_pos & (np.array(recs['cmmrf']) >= (p85 if p85 is not None else -1e9))

    subs = {'fusion': np.ones(m, bool), 'f3f': strong_mask, 'cmmr': cmmr_pos,
            'cmmrf': cmmrf_mask, 'center': ct_strong_mask, 'dual': np.ones(m, bool)}

    for s in sources:
        v = np.array(recs[s], dtype=float)
        # 该源当日无评分行（信号表未上线）→ 跳过该源该日
        if not any(abs(x) > 1e-12 for x in v):
            continue
        ic_all = spearmanr(v, ret).correlation
        sm = subs[s]
        acc[s]['n_sub'].append(int(sm.sum()))
        acc[s]['ic_all'].append(float(ic_all) if not np.isnan(ic_all) else np.nan)
        acc[s]['ic_sub'].append(float(spearmanr(v[sm], ret[sm]).correlation) if sm.sum() >= 30 else np.nan)
        idx = np.where(sm)[0]
        top = idx[np.argsort(v[idx])[::-1][:10]]
        acc[s]['top10'].append(float(ret[top].mean() * 100))
        acc[s]['mkt'].append(mkt)

print()
print('%-8s %6s %9s %9s %9s %9s' % ('信号源', '子集n', '全截面IC', '子集IC', 'Top10%', '市场%'))
for s in sources:
    a = acc[s]
    if not a['ic_all']:
        continue
    print('%-8s %6.0f %+9.4f %+9.4f %+9.2f %+9.2f' % (
        s, np.mean(a['n_sub']), np.nanmean(a['ic_all']), np.nanmean(a['ic_sub']),
        np.mean(a['top10']), np.mean(a['mkt'])))
print('\n窗口数:', len(mature), '（Top10/市场=20d等权收益均值；子集=执行口径过滤后票池）')