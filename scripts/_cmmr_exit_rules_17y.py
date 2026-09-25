#!/usr/bin/env python3
"""CMMR 退出规则对拍（09-13）：修复兑现中途TP vs 固定20日重评 vs 10日重评
原理问题：cmmr 设计赌的是"趋势未破+10日超卖→修复行情"，修复段实测~10日走完，
20日重评原教旨让回吐期全暴露。本回测=重放17年打分，对拍不同退出规则。

打分严格按生产 cmmr_standalone.py 逐字复刻（原始收盘价口径，非复权）：
  trend: ma40_slope=(ma40-ma40[shift20])/ma40[shift20]; >0.02→40, 0<s≤0.02→20
  oversold: pct_chg_10d<-0.08→40, -0.08~‑0.04→20   (真实10日涨跌幅)
  vol: vol_ratio<0.8 或 (>1.2且close>open)→20 否则0 (量比=当日量/近5日均量含当日)
  红线: slope<0 → 0
收益用复权收盘（close*adj_factor）。信号日收盘打分，次日收盘入场。
成本0.1%/边 计入买卖当日组合收益。停牌持有期间用ffill价。
选池（17年无fusion次级键，统一确定性代理）：score≥80 按 (score降,pct10升=回调最深) 取前10。
变体：V10 / V20（现行） / V20+TP5 / V20+TP8（浮盈≥5%/8%次日收盘落袋，空仓等重评日）。
基准=全可交易域等权。输出各变体 年化超额/日超额t/逐年超额/换手/平均持有天数。
"""
import duckdb, sqlite3, os, sys, numpy as np, pandas as pd
HOME = os.path.expanduser('~')
DB = f'{HOME}/.hermes/stockdb/tushare.db'
SIG = f'{HOME}/.hermes/stockdb/signals.db'

# ---------- 数据 ----------
con = duckdb.connect(DB, read_only=True)
bad = set()
sc = sqlite3.connect(SIG)
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8','4','92')):
        bad.add(str(code))
print(f'ST/退市/北交所剔除: {len(bad)}')

START = sys.argv[1] if len(sys.argv) > 1 else '20090101'
df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) AS td, d."open", d.close, d.vol, a.adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE d.trade_date >= '{START}'
""").df()
print('rows:', len(df))
keep = ~df.ts_code.str[:6].isin(bad)
df = df[keep]
col_order = sorted(df.ts_code.unique())
close = df.pivot(index='td', columns='ts_code', values='close').reindex(columns=col_order).astype('float32')
opn   = df.pivot(index='td', columns='ts_code', values='open').reindex(columns=col_order).astype('float32')
vol   = df.pivot(index='td', columns='ts_code', values='vol').reindex(columns=col_order).astype('float32')
adjf  = df.pivot(index='td', columns='ts_code', values='adj_factor').reindex(columns=col_order).astype('float32')
adjf  = adjf.ffill().fillna(1.0)
cal = list(close.index)
ci = {d: i for i, d in enumerate(cal)}
C = close.values; A = (close * adjf).values  # 复权收盘(原始close缺失→nan, ffill在收益里处理)
idx = pd.Index(col_order)
print('cal:', len(cal), cal[0], '->', cal[-1])

# ---------- 打分重放（与生产同口径：原始价） ----------
ma40 = close.rolling(40, min_periods=40).mean()
slope = (ma40 - ma40.shift(20)) / ma40.shift(20)
pct10 = close / close.shift(10) - 1
v5 = vol.rolling(5, min_periods=1).mean()
vr = vol / v5.replace(0, np.nan)
trend = np.where(slope > 0.02, 40, np.where(slope > 0, 20, 0))
overs = np.where(pct10 < -0.08, 40, np.where(pct10 < -0.04, 20, 0))
vsc = np.where((vr < 0.8) | ((vr > 1.2) & (C > opn)), 20, 0)
score = trend + overs + vsc
score = np.where((slope < 0).values, 0, score)
score[~np.isfinite(C)] = 0
S = score.astype(np.int16)
P10 = pct10.values.astype('float32')
tradable_raw = np.isfinite(C)          # 当日有原始行=可交易判定
A_ff = pd.DataFrame(A).ffill().values   # 持有期用ffill复权价

# ---------- 对账：与 signal_history 生产分逐票比 ----------
chk = sc.execute("SELECT REPLACE(date,'-',''), stock_code, cmmr_score FROM signal_history WHERE cmmr_score>0 AND date>='2026-08-01'").fetchall()
match = tot = 0
for dstr, code, cs in chk:
    t = int(dstr)
    ts = code + ('.SH' if code.startswith(('6','9')) else '.SZ')
    if t in ci and ts in idx:
        j = idx.get_loc(ts)
        if ci[t] < len(cal):
            tot += 1
            if float(S[ci[t], j]) == float(cs or 0): match += 1
print(f'对账 signal_history≥80时代: {match}/{tot} 一致 = {100*match/max(tot,1):.1f}%')

# ---------- 每日 top10（信号日收盘，用 score≥80，(score降, pct10升)排序） ----------
top10 = {}
for i, d in enumerate(cal):
    s = S[i]
    ok = np.where((s >= 80) & tradable_raw[i])[0]
    if len(ok) == 0: top10[d] = []; continue
    order = np.lexsort((np.nan_to_num(P10[i][ok], nan=0.0), -s[ok]))
    top10[d] = list(ok[order][:10])

# ---------- 引擎 ----------
# 毒数据过滤：新股连板/除权错位造成的异常日收益。A股主板±10/创业板±20，
# 剔除|ret|>25%；且剔除每票上市前11个交易日（新股炒作段）。
_ret = A_ff / np.roll(A_ff, 1, axis=0) - 1
age = np.cumsum(np.isfinite(A_ff), axis=0)          # 每票截至当日的出现天数
ok_ret = np.isfinite(_ret) & (np.abs(_ret) <= 0.25) & (age >= 11)
ok_ret[0] = False

def run(R, TP=None, cost=0.001):
    """等权组合：每票权重1/10。r=Σ(单票日收益/10)。TP按单票浮盈触发。"""
    hold = {}   # col -> (entry_A, entry_day_i)
    pending = []  # 收盘挂买 [col]
    rets = np.full(len(cal), np.nan); ntr = 0; holds = []; rebal_i = None
    for i in range(1, len(cal)):
        d = cal[i]
        r = 0.0
        for col in hold:
            if ok_ret[i, col]:
                r += _ret[i, col] / 10
        if hold: rets[i] = r
        # 开盘前无操作；收盘执行昨日挂单买入
        if pending:
            bought = [c for c in pending if np.isfinite(A_ff[i, c])]
            for c in bought: hold[c] = (A_ff[i, c], i)
            ntr += len(bought)
            if bought: rets[i] = (rets[i] if np.isfinite(rets[i]) else 0.0) - cost * len(bought) / 10
            pending = []
        # 收盘决策
        need_rebal = (rebal_i is None) or (i - rebal_i >= R)
        sells = set()
        if TP is not None:
            for col, (ea, ei) in hold.items():
                if np.isfinite(A_ff[i, col]) and A_ff[i, col] / ea - 1 >= TP:
                    sells.add(col)
        if need_rebal and top10.get(d) is not None:
            rebal_i = i
            keep_new = set(top10[d])
            for c in list(hold.keys()):
                if c not in keep_new: sells.add(c)
        if sells:
            for c in sells:
                holds.append(i - hold[c][1]); hold.pop(c, None)
            ntr += len(sells)
            rets[i] = (rets[i] if np.isfinite(rets[i]) else 0.0) - cost * len(sells) / 10
        if need_rebal and top10.get(d) is not None:
            pending = [c for c in top10[d] if c not in hold]
    return rets, ntr, (np.mean(holds) if holds else np.nan)

# 基准：全可交易域等权（与组合同一套毒数据过滤 ok_ret）
bench = np.full(len(cal), np.nan)
for i in range(1, len(cal)):
    m = tradable_raw[i-1] & ok_ret[i]
    if m.sum() > 50: bench[i] = np.nanmean(_ret[i][m])

print(f"\n{'变体':<10}{'年化超额%':>9}{'日超额t':>9}{'最大回撤%':>9}{'笔/年':>7}{'持有日':>7}")
import json
out = {}
years = sorted(set(str(d)[:4] for d in cal[30:]))
yearly = {}
for name, R, TP in [('V10',10,None), ('V20',20,None), ('V20+TP5',20,0.05), ('V20+TP8',20,0.08),
                    ('V20+TP3',20,0.03), ('V40',40,None), ('V40+TP5',40,0.05)]:
    rets, ntr, hd = run(R, TP)
    exc = rets[1:] - bench[1:]
    m = np.isfinite(exc)
    mu, sd = exc[m].mean(), exc[m].std()
    t = mu / (sd / np.sqrt(m.sum())) if sd > 0 else 0
    nav = np.cumprod(1 + np.nan_to_num(rets[1:])); bnav = np.cumprod(1 + np.nan_to_num(bench[1:]))
    rel = nav - bnav
    dd = (rel - np.maximum.accumulate(rel)).min()
    ny = len(cal) / 244
    yrs_arr = np.array(cal[1:]) // 10000
    yearly[name] = {y: 100*float(np.nansum(exc[m & (yrs_arr == int(y))])) for y in years}
    print(f'{name:<10}{100*mu*244:>9.2f}{t:>9.2f}{100*dd:>9.1f}{ntr/ny:>7.0f}{hd:>7.1f}')
    out[name] = dict(exc_ann=float(mu*244*100), t=float(t))
with open(f'{HOME}/.hermes/stockdb/replay/_cmmr_exit_rules_17y.json','w') as f:
    json.dump(dict(yearly=yearly, summary=out, cal=[str(cal[0]),str(cal[-1])]), f, ensure_ascii=False)
print('\n逐年超额%:')
print('变体      ' + ''.join(f'{y:>8}' for y in years))
for name in yearly:
    print(f'{name:<10}' + ''.join(f'{yearly[name][y]:>8.1f}' for y in years))
