#!/usr/bin/env python3
"""反向实验：中枢'强买'池内用cmmr分筛，收益差多少？
每信号日：pool = fusion_center_signals signal='强买'（剔ST/北交所，需有cmmr分）。
cmmr 6档离散(0/20/40/60/80/100)，池内同分并列→按整档分组；
组内随机抽10只（重复50次取均值）算等权前瞻收益，消除同分抽签噪声。
输出：cmmr-Top10(高分档) / cmmr-Bottom10(低分档) / 整池 / 市场，10d+20d。8月+9月初信号日。"""
import sqlite3, duckdb, numpy as np
rng = np.random.default_rng(42)
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in td.execute("SELECT DISTINCT trade_date FROM daily ORDER BY 1").fetchall()]
tidx = {d: i for i, d in enumerate(tdays)}
bad = set()
for sc, nm, mk in st.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(str(sc))

def sample_mean(codes_rets, k=10, reps=50):
    """从{code:ret}抽k只等权收益，reps次取均值（池<=k则全取）。"""
    v = list(codes_rets.values())
    if len(v) <= k:
        return np.mean(v)
    return np.mean([np.mean(rng.choice(v, k, replace=False)) for _ in range(reps)])

sig_dates = [str(r[0]) for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM fusion_center_signals ORDER BY 1").fetchall()]

for H in (10, 20):
    print(f'\n===== 中枢强买池 x cmmr筛  前瞻{H}日 =====')
    print('日期       池n  cmmrTop10  cmmrBot10  整池    市场    Top超额  Bot超额  池内cmmr档位分布(n:分)')
    agg = {'t': [], 'b': [], 'p': [], 'm': []}
    band = {}   # cmmr档位 -> 池内等权超额收益列表（全信号日汇总）
    nd = 0
    for sd in sig_dates:
        if tidx.get(sd) is None or tidx[sd] + H >= len(tdays):
            continue
        end = tdays[tidx[sd] + H]
        p0 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (sd,)).fetchall()}
        p1 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (end,)).fetchall()}
        ret = {ts[:6]: (p1[ts] / v - 1) * 100 for ts, v in p0.items()
               if v > 0 and ts in p1 and ts[:6] not in bad}
        mret = np.mean(list(ret.values()))
        rows = st.execute("""
            SELECT c.stock_code, c.score FROM fusion_center_signals c
            JOIN signal_history s ON s.stock_code = c.stock_code
             AND REPLACE(s.date,'-','') = REPLACE(c.date,'-','')
            WHERE REPLACE(c.date,'-','')=? AND c.signal='强买' AND s.cmmr_score IS NOT NULL""", (sd,)).fetchall()
        pool = [(str(c), float(sc)) for c, sc in rows if str(c) in ret]
        if len(pool) < 20:
            continue
        by_band = {}
        for c, _ in pool:
            cs = st.execute("SELECT cmmr_score FROM signal_history WHERE REPLACE(date,'-','')=? AND stock_code=?", (sd, c)).fetchone()[0]
            by_band.setdefault(float(cs or 0), []).append(c)
        bands_sorted = sorted(by_band)
        top_codes, bot_codes = [], []
        for b in reversed(bands_sorted):        # 高分往低分取满10
            if len(top_codes) < 10:
                top_codes += by_band[b]
            if len(bot_codes) < 10:             # 低分往高分取满10
                bot_codes += by_band[b]
        top = sample_mean({c: ret[c] for c in top_codes[:max(10, len(by_band[bands_sorted[-1]]))]})
        bot = sample_mean({c: ret[c] for c in bot_codes[:max(10, len(by_band[bands_sorted[0]]))]})
        allp = sample_mean({c: ret[c] for c, _ in pool}, k=min(10, len(pool)), reps=20)
        dist = " ".join(f"{b:.0f}:{len(by_band[b])}" for b in bands_sorted)
        print(f"{sd}  {len(pool):5d}  {top:+8.2f}  {bot:+9.2f}  {allp:+7.2f}  {mret:+6.2f}  {top-mret:+7.2f}  {bot-mret:+7.2f}  {dist}")
        agg['t'].append(top - mret); agg['b'].append(bot - mret); agg['p'].append(allp - mret); agg['m'].append(mret)
        for b in bands_sorted:
            if len(by_band[b]) >= 5:  # 档位内>=5只才统计整档
                band.setdefault(b, []).append(sample_mean({c: ret[c] for c in by_band[b]}, k=min(10, len(by_band[b])), reps=20) - mret)
        nd += 1
    if nd:
        print(f"均值(n={nd}): 超额 Top {np.mean(agg['t']):+.2f}  Bottom {np.mean(agg['b']):+.2f}  整池 {np.mean(agg['p']):+.2f}  Top-Bot {np.mean(agg['t'])-np.mean(agg['b']):+.2f}pp")
        print("整档超额(档位: 均值pp, 天数):", {f"{b:.0f}": f"{np.mean(v):+.2f}({len(v)}d)" for b, v in sorted(band.items())})
        w = sum(1 for a, c in zip(agg['t'], agg['p']) if a > c)
        print(f"Top10跑赢整池(抽10只)天数: {w}/{nd}")