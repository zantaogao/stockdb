# -*- coding: utf-8 -*-
"""窗口网格 + 权重网格 重做（基准修正版，2026-09-21）

动机（2026-09-21 核验发现两处会让结论失真的问题）：
 1) adj_factor 表 2015 前缺失（覆盖率 0.0%）→ 前 6 年是坏样本；本脚本用
    backtest_results/adj_factor_pre2015.parquet 补丁（UNION 读取，主库保持只读）修好。
 2) 9/11 与 9/20 的"超额"基准：9/20 CMMR 网格用**横截面中位数**（不可投资）→ 超额被高估
    （实测中位 -0.573%/10日 vs 等权均值 +0.424%/10日，差 1.0pp）。
    本脚本两种基准都算，直接给出"结论是否反转"。

输出：
 表A 窗口网格（R=5/10/15/20/30/40）：毛/周期、净/日（显性/滑点0.1/滑点0.2）、年化、正年数
     —— 对应 9/11「中枢 10→20 日」决策的同口径重做（名单用可复现的 CMMR，非中枢）
 表B 权重网格对比：CMMR 三腿权重 66 组 + 候选，在**两种基准**下的超额与 NW-t
     —— 对应 9/20 权重网格的重做
"""
import os
import sqlite3
import time

import duckdb
import numpy as np
import pandas as pd

HOME = os.path.expanduser('~')
BASE = f'{HOME}/.hermes/stockdb'
DB = f'{BASE}/tushare.db'
SIG = f'{BASE}/signals.db'
PATCH = f'{BASE}/backtest_results/adj_factor_pre2015.parquet'
START = os.environ.get('START_DATE', '20090101')
END = os.environ.get('END_DATE', '20260918')
OUTDIR = f'{BASE}/analysis'
TO = 0.85
COST = {'显性': TO * (0.03 + 0.03 + 0.05),
        '滑点0.1': TO * ((0.03 + 0.1) * 2 + 0.05),
        '滑点0.2': TO * ((0.03 + 0.2) * 2 + 0.05)}

t0 = time.time()
os.makedirs(OUTDIR, exist_ok=True)
has_patch = os.path.exists(PATCH)
adj_sql = ("COALESCE(a.adj_factor, p.adj_factor)" if has_patch else "a.adj_factor")
patch_join = (f"LEFT JOIN read_parquet('{PATCH}') p USING (ts_code, trade_date)" if has_patch else "")
print(f'adj_factor 补丁: {"已加载 " + PATCH if has_patch else "未找到（2015 前仍缺）"}', flush=True)

con = duckdb.connect(DB, read_only=True)
con.execute("SET memory_limit='24GB'")
bad = set()
sc = sqlite3.connect(f'file:{SIG}?mode=ro', uri=True)
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8', '4', '92')):
        bad.add(str(code))
sc.close()
df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) AS td, d."open", d.close, d.vol, {adj_sql} AS adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  {patch_join}
  WHERE d.trade_date >= '{START}' AND d.trade_date <= '{END}'
""").df()
con.close()
df = df[~df.ts_code.str[:6].isin(bad)]
col_order = sorted(df.ts_code.unique())


def piv(col):
    return (df.pivot(index='td', columns='ts_code', values=col)
              .reindex(columns=col_order).astype('float32'))


close = piv('close')
opn = piv('open')
vol = piv('vol')
adjf = piv('adj_factor').ffill()
_rw = (close * adjf).values
_rr = np.zeros_like(_rw)
_rr[1:] = np.where(_rw[:-1] > 0, _rw[1:] / np.where(_rw[:-1] > 0, _rw[:-1], np.nan) - 1, np.nan)
_bad = np.abs(np.nan_to_num(_rr, nan=0.0)) > 0.21
A_ff = pd.DataFrame(np.where(_bad, np.nan, _rw), index=close.index).ffill().values
cal = list(close.index)
n = len(cal)
print(f'cal {n}  {cal[0]}->{cal[-1]}  异常夹紧 {int(_bad.sum())}  {time.time()-t0:.0f}s', flush=True)

ma40 = close.rolling(40).mean()
ma40p = close.rolling(20).mean().shift(40)
S = ((ma40 - ma40p) / ma40p).values
P = (close / close.shift(10) - 1).values
R_ = (vol / vol.rolling(5).mean()).values
enough = (close.rolling(60).count().values >= 60)
O_, C_ = opn.values, close.values
T = np.where(S > 0.02, 1.0, np.where(S > 0, 0.5, 0.0)).astype('float32')
Ov = np.where(P < -0.08, 1.0, np.where(P < -0.04, 0.5, 0.0)).astype('float32')
V = np.where((R_ < 0.8) | ((R_ > 1.2) & (C_ > O_)), 1.0, 0.0).astype('float32')
kill = (S < 0) | ~enough | np.isnan(C_)
T[kill] = 0
Ov[kill] = 0
V[kill] = 0
years = np.array([d // 10000 for d in cal])
weeks = np.full(len(cal), -1, 'int32')
for k, d in enumerate(cal):
    weeks[k] = d // 100 if False else 0

print(f'因子就绪  {time.time()-t0:.0f}s', flush=True)


def top10_of(score, i):
    pool = np.where(score[i] >= 0.8)[0]
    if len(pool) < 10:
        return None
    ps, pp = score[i][pool], P[i, pool]
    ok = ~np.isnan(pp)
    ps, pp, idx = ps[ok], pp[ok], pool[ok]
    if len(ps) < 10:
        return None
    return idx[np.lexsort((pp, -ps))[:10]]


# 市场等权（均值）R 日收益矩阵：mktR[i] = 从 i 到 i+R 的全市场等权收益
MAXR = 60
mk = {}
for R in [5, 10, 15, 20, 30, 40]:
    m = np.full(n, np.nan)
    for i in range(60, n - R):
        f = A_ff[i + R] / np.where(A_ff[i] > 0, A_ff[i], np.nan) - 1
        f = np.where(np.isnan(A_ff[i]) | np.isnan(A_ff[i + R]), np.nan, f)
        f = f[np.abs(f) <= 1.0]
        if len(f) > 500:
            m[i] = f.mean()
    mk[R] = m
print(f'市场 R 日收益就绪  {time.time()-t0:.0f}s', flush=True)


def top_r_ret(sel_idx, i, R):
    f = A_ff[i + R][sel_idx] / np.where(A_ff[i][sel_idx] > 0, A_ff[i][sel_idx], np.nan) - 1
    f = f[~np.isnan(f)]
    return f.mean() if len(f) >= 8 else np.nan


# ── 表A：窗口网格（毛/净 超额，两种基准）──
print('\n' + '=' * 118)
print(f'【表A】窗口网格（名单=CMMR40/40/20 top10，非重叠采样，样本 {cal[60]}~{cal[-1]}）')
print('=' * 118)
print(f"{'R':>4}{'周期数':>8}{'毛/周期·均值基准':>18}{'毛/周期·中位基准':>18}{'非重叠t(均值)':>14}"
      f"{'净/日·显性':>12}{'净/日·滑点0.1':>14}{'净/日·滑点0.2':>14}{'年化净0.1':>11}{'正年数':>9}")
scoreA = (40 * T + 40 * Ov + 20 * V) / 100.0
rowsA = []
for R in [5, 10, 15, 20, 30, 40]:
    ex_mean, ex_med, ts_, yl = [], [], [], []
    for o in range(R):
        idxs = [i for i in range(60 + o, n - R, R)]
        v_m, v_d, yy = [], [], []
        for i in idxs:
            sel = top10_of(scoreA, i)
            if sel is None:
                continue
            r = top_r_ret(sel, i, R)
            if np.isnan(r) or np.isnan(mk[R][i]):
                continue
            f = A_ff[i + R] / np.where(A_ff[i] > 0, A_ff[i], np.nan) - 1
            f = np.where(np.isnan(f), np.nan, f)
            f = f[np.abs(np.nan_to_num(f)) <= 1.0]
            med = float(np.nanmedian(f)) if len(f) > 500 else np.nan
            if np.isnan(med):
                continue
            v_m.append(r - mk[R][i])
            v_d.append(r - med)
            yy.append(years[i])
        if len(v_m) >= 10:
            ex_mean += v_m
            ex_med += v_d
            yl += yy
            a = np.array(v_m)
            ts_.append(a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if a.std(ddof=1) > 0 else 0.0)
    if not ex_mean:
        continue
    gm, gd = np.mean(ex_mean) * 100, np.mean(ex_med) * 100
    t_ = float(np.mean(ts_)) if ts_ else 0.0
    net = {k: (gm - c) / R for k, c in COST.items()}
    ann = ((1 + net['滑点0.1'] / 100) ** 243 - 1) * 100
    yl = np.array(yl)
    ym = {y: (np.mean(np.array(ex_mean)[yl == y]) * 100 - COST['滑点0.1']) / R
          for y in sorted(set(yl)) if (yl == y).sum() >= 30}
    posy = sum(1 for v in ym.values() if v > 0)
    print(f"{R:>4}{len(ex_mean):>8}{gm:>+18.3f}{gd:>+18.3f}{t_:>+14.1f}"
          f"{net['显性']:>+12.4f}{net['滑点0.1']:>+14.4f}{net['滑点0.2']:>+14.4f}{ann:>+10.1f}%{posy:>5}/{len(ym):<3}")
    rowsA.append(dict(R=R, n=len(ex_mean), gross_mean=gm, gross_med=gd, t=t_, net_explicit=net['显性'],
                      net_slip01=net['滑点0.1'], net_slip02=net['滑点0.2'], ann=ann,
                      pos_years=f'{posy}/{len(ym)}', yr=ym))
pd.DataFrame([{k: v for k, v in r.items() if k != 'yr'} for r in rowsA]).to_csv(
    f'{OUTDIR}/grid_window_fixed_0921.csv', index=False)

# ── 表B：权重网格（两种基准对比）──
print('\n' + '=' * 118)
print('【表B】CMMR 三腿权重网格（10 日，非重叠；两种基准并列）')
print('=' * 118)
WEIGHTS = {}
for w1 in range(0, 101, 10):
    for w2 in range(0, 101 - w1, 10):
        WEIGHTS[f'{w1}/{w2}/{100-w1-w2}'] = (w1, w2, 100 - w1 - w2)
for extra in [(40, 40, 20), (40, 20, 40), (20, 40, 40), (50, 30, 20), (30, 40, 30), (33, 34, 33)]:
    WEIGHTS['H' + '/'.join(map(str, extra))] = extra


def nw_t(v, lag=10):
    v = np.asarray(v)
    n = len(v)
    if n < 10:
        return 0.0
    m = v.mean()
    e = v - m
    g = sum(np.cov(e[j:], e[:-j], ddof=1)[0, 1] * (1 - j / (lag + 1)) for j in range(1, lag + 1))
    return m / np.sqrt((np.var(v, ddof=1) + 2 * g) / n)


R = 10
idxs = [i for i in range(60, n - R, R)]
resB = []
for name, w in sorted(WEIGHTS.items()):
    wt, wo, wv = w
    tot = wt + wo + wv
    if tot == 0:
        continue
    sc_all = (wt * T + wo * Ov + wv * V) / tot
    exm, exd = [], []
    for i in idxs:
        sel = top10_of(sc_all, i)
        if sel is None:
            continue
        r = top_r_ret(sel, i, R)
        if np.isnan(r) or np.isnan(mk[R][i]):
            continue
        f = A_ff[i + R] / np.where(A_ff[i] > 0, A_ff[i], np.nan) - 1
        f = np.where(np.isnan(f), np.nan, f)
        f = f[np.abs(np.nan_to_num(f)) <= 1.0]
        med = float(np.nanmedian(f)) if len(f) > 500 else np.nan
        if np.isnan(med):
            continue
        exm.append(r - mk[R][i])
        exd.append(r - med)
    if len(exm) < 50:
        continue
    resB.append(dict(w=name, n=len(exm),
                     ex_mean=np.mean(exm) * 100, ex_med=np.mean(exd) * 100,
                     t_mean=nw_t(np.array(exm) * 100), t_med=nw_t(np.array(exd) * 100),
                     net_mean=(np.mean(exm) * 100 - COST['显性']) / R,
                     net_med=(np.mean(exd) * 100 - COST['显性']) / R))
B = pd.DataFrame(resB)
B['rank_mean'] = B.ex_mean.rank(ascending=False)
B['rank_med'] = B.ex_med.rank(ascending=False)
B.to_csv(f'{OUTDIR}/grid_weight_fixed_0921.csv', index=False)
pd.set_option('display.width', 200)
print(B.sort_values('ex_mean', ascending=False).head(12).to_string(
    index=False, columns=['w', 'n', 'ex_mean', 't_mean', 'net_mean', 'ex_med', 't_med', 'rank_mean', 'rank_med']))
print('\n两种基准下的最优权重：')
print('  均值基准（可投资）→ ', B.loc[B.ex_mean.idxmax(), 'w'], f"（超额 {B.ex_mean.max():+.3f}%/10日）")
print('  中位基准（9/20 用的）→ ', B.loc[B.ex_med.idxmax(), 'w'], f"（超额 {B.ex_med.max():+.3f}%/10日）")
sp = B[['w', 'rank_mean', 'rank_med']].copy()
sp['drank'] = (sp.rank_mean - sp.rank_med).abs()
print(f'  两者排名差异：最大 {int(sp.drank.max())} 位，平均 {sp.drank.mean():.1f} 位（共 {len(B)} 组）')
print(f'\n明细 → {OUTDIR}/grid_window_fixed_0921.csv / grid_weight_fixed_0921.csv   {time.time()-t0:.0f}s')
