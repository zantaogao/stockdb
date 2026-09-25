#!/usr/bin/env python3
"""CMMR系+中枢 排序形态分析（成熟20d窗口）
问题：中枢(三因子变体)是否继承U型排序失效？cmmr/cmmrf自身排序形态？
方法：每源在 [全截面] 与 [执行子集] 两池内按分数升序分10组(D1低~D10高)，
     各组等权20d收益减当日市场等权 → 跨日平均。
判定：首尾差(D10-D1)、单调ρ(Spearman组序,组收益)、最低组位置(U型=最低在中部且D1次低)。
子集口径与产线一致：cmmr=score>0；cmmrf=>0且≥p85；center/f3f=signal='强买'。"""
import sqlite3
import numpy as np
from scipy.stats import spearmanr

st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
import duckdb
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

tdays = [str(r[0]) for r in td.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
tidx = {d: i for i, d in enumerate(tdays)}
sig_dates = [str(r[0]) for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
mature = [d for d in sig_dates if d in tidx and tidx[d] + 20 < len(tdays)]
print('成熟20d窗口:', len(mature), mature[0], '~', mature[-1])

bad = set()
for sc, nm, mk in st.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(str(sc))

def code_to_ts(c):
    return c + ('.SH' if c.startswith(('6', '9')) else '.SZ')

SRCS = ['cmmr', 'cmmrf', 'center', 'f3f', 'fusion']
res = {s: {'all': {i: [] for i in range(1, 11)},
           'sub': {i: [] for i in range(1, 11)}} for s in SRCS}
nsub = {s: {'all': [], 'sub': []} for s in SRCS}

for sd in mature:
    end = tdays[tidx[sd] + 20]
    sig = st.execute(
        "SELECT stock_code, fusion_score, cmmr_score, fusion_score_cmmr FROM signal_history "
        "WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    if not sig:
        continue
    ct_rows = st.execute(
        "SELECT stock_code, score, signal FROM fusion_center_signals "
        "WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    f3_rows = st.execute(
        "SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals "
        "WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    # 注：center/f3f表上线晚，缺行的日子只跳过这两个源，不拖累cmmr/cmmrf/fusion

    p0 = {r[0]: float(r[1]) for r in td.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=?", (sd,)).fetchall()}
    p1 = {r[0]: float(r[1]) for r in td.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=?", (end,)).fetchall()}

    # 当日市场等权基准（与ic_window口径一致：全部可算票剔bad）
    mrets = [(p1[t] / p0[t] - 1) * 100 for t in p0
             if t in p1 and t[:6] not in bad and p0[t] > 0]
    mret = np.mean(mrets)

    ret_by_code, score = {}, {s: {} for s in SRCS}
    for code, fs, cs, fcs in sig:
        ts = code_to_ts(str(code))
        if ts in p0 and ts in p1 and p0[ts] > 0 and str(code) not in bad:
            ret_by_code[str(code)] = (p1[ts] / p0[ts] - 1) * 100
    for code, fs, cs, fcs in sig:
        score['fusion'][str(code)] = float(fs or 0)
        score['cmmr'][str(code)] = float(cs or 0)
        score['cmmrf'][str(code)] = float(fcs or 0)
    for code, sc_, sg in ct_rows:
        score['center'][str(code)] = float(sc_ or 0)
    for code, sc_, sg in f3_rows:
        score['f3f'][str(code)] = float(sc_ or 0)
    ct_strong = {str(r[0]) for r in ct_rows if r[2] == '强买'}
    f3_strong = {str(r[0]) for r in f3_rows if r[2] == '强买'}

    pools = {}
    for src in SRCS:
        pool_all = {c: ret_by_code[c] for c in score[src] if c in ret_by_code}
        # 有效性过滤：该源当日去重分数<5个 = 未上线占位期（如cmmr 7/28前大面积0分），跳过
        if len({score[src][c] for c in pool_all}) < 5:
            pool_all = {}
        if src == 'cmmr':
            sub = {c: v for c, v in pool_all.items() if score['cmmr'][c] > 0}
        elif src == 'cmmrf':
            posv = [score['cmmrf'][c] for c in pool_all if score['cmmrf'][c] > 0]
            if len(posv) >= 20:
                p85 = np.percentile(posv, 85)
                sub = {c: v for c, v in pool_all.items() if score['cmmrf'][c] >= p85}
            else:
                sub = {}
        elif src == 'center':
            sub = {c: ret_by_code[c] for c in ct_strong if c in ret_by_code}
        elif src == 'f3f':
            sub = {c: ret_by_code[c] for c in f3_strong if c in ret_by_code}
        else:
            sub = pool_all
        pools[src] = {'all': pool_all, 'sub': sub}

    for src in SRCS:
        for scope in ('all', 'sub'):
            pool = pools[src][scope]
            if len(pool) < 20:
                continue
            nsub[src][scope].append(len(pool))
            items = sorted(pool.items(), key=lambda kv: score[src][kv[0]])
            n = len(items)
            for i in range(10):
                grp = items[i * n // 10:(i + 1) * n // 10]
                if grp:
                    res[src][scope][i + 1].append(np.mean([v for _, v in grp]) - mret)

print('\n=== 十分位等权20d超额收益（%，已扣当日市场等权，跨日均值）===')
print('池: all=全截面 sub=执行子集 | D1分最低 … D10分最高')
for src in SRCS:
    for scope in ('all', 'sub'):
        row = [np.mean(res[src][scope][i]) if res[src][scope][i] else np.nan
               for i in range(1, 11)]
        arr = np.array(row)
        nd = max(len(res[src][scope][i]) for i in range(1, 11))
        ns = int(np.mean(nsub[src][scope])) if nsub[src][scope] else 0
        mono = spearmanr(np.arange(1, 11), arr).correlation
        trough = int(np.nanargmin(arr)) + 1
        u_shape = arr[0] - arr[trough - 1] if 1 < trough < 10 else np.nan  # D1高出最低组多少（U型左翼强度）
        print(f"{src:7s} {scope:3s} 日数={nd:2d} 池n={ns:4d}  " +
              " ".join(f"D{i}={arr[i-1]:+5.2f}" for i in range(1, 11)) +
              f"  首尾差={arr[-1]-arr[0]:+5.2f} 单调ρ={mono:+5.2f} 最低组=D{trough}" +
              (f" 左翼高出谷底={u_shape:+.2f}" if not np.isnan(u_shape) else ""))
st.close(); td.close()