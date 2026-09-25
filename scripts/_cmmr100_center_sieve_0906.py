#!/usr/bin/env python3
"""实验：8月 cmmr=100 分票池内再用中枢分筛，收益差多少？
每个信号日：pool = cmmr_score==100 且当日有中枢分（剔ST/北交所）。
分组：中枢Top10（分最高=离中枢最近） / 中枢Bottom10（分最低） / 整池等权 / 全市场等权。
前瞻：10d（信号日8/6~最后满10d日）+ 20d（仅成熟日）。中枢表8/6建，起点即8/6。
中枢分是连续分（负数，越接近0越高），不存在并列抽签问题。"""
import sqlite3, duckdb, numpy as np
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in td.execute("SELECT DISTINCT trade_date FROM daily ORDER BY 1").fetchall()]
tidx = {d: i for i, d in enumerate(tdays)}
bad = set()
for sc, nm, mk in st.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(str(sc))

def fwd_ret(sig_d, h):
    """返回 {裸码: h交易日前瞻收益%}（当日收盘→h日后收盘），和市场等权。"""
    if tidx[sig_d] + h >= len(tdays):
        return None, None
    end = tdays[tidx[sig_d] + h]
    p0 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (sig_d,)).fetchall()}
    p1 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (end,)).fetchall()}
    ret = {}
    for ts, v in p0.items():
        if v > 0 and ts in p1 and ts[:6] not in bad:
            ret[ts[:6]] = (p1[ts] / v - 1) * 100
    return ret, np.mean(list(ret.values()))

sig_dates = [str(r[0]) for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history WHERE REPLACE(date,'-','') BETWEEN '20260801' AND '20260831' ORDER BY 1").fetchall()]

for H in (10, 20):
    print(f'\n===== 前瞻 {H} 交易日 =====')
    print('日期       池n  中枢Top10  中枢Bottom10  整池均值  市场   Top10超额  Bottom超额  Top-Bot差')
    agg = {'t': [], 'b': [], 'p': [], 'm': []}
    nd = 0
    for sd in sig_dates:
        ret, mret = fwd_ret(sd, H)
        if ret is None:
            continue
        rows = st.execute("""
            SELECT s.stock_code, c.score FROM signal_history s
            JOIN fusion_center_signals c ON c.stock_code = s.stock_code
             AND REPLACE(c.date,'-','') = REPLACE(s.date,'-','')
            WHERE REPLACE(s.date,'-','')=? AND s.cmmr_score = 100""", (sd,)).fetchall()
        pool = [(str(c), float(sc)) for c, sc in rows if str(c) in ret]
        if len(pool) < 20:
            continue
        pool.sort(key=lambda x: -x[1])
        top = np.mean([ret[c] for c, _ in pool[:10]])
        bot = np.mean([ret[c] for c, _ in pool[-10:]])
        allp = np.mean([ret[c] for c, _ in pool])
        agg['t'].append(top - mret); agg['b'].append(bot - mret)
        agg['p'].append(allp - mret); agg['m'].append(mret)
        nd += 1
        print(f"{sd}  {len(pool):4d}  {top:+8.2f}  {bot:+10.2f}  {allp:+8.2f}  {mret:+6.2f}  {top-mret:+8.2f}  {bot-mret:+9.2f}  {top-bot:+9.2f}")
    if nd:
        print(f"均值(n={nd}):                            " +
              f"超额: Top {np.mean(agg['t']):+.2f}pp  Bottom {np.mean(agg['b']):+.2f}pp  整池 {np.mean(agg['p']):+.2f}pp  " +
              f"Top-Bot {np.mean(agg['t'])-np.mean(agg['b']):+.2f}pp")
        # 胜率：Top跑赢池子的天数
        w = sum(1 for a, b in zip(agg['t'], agg['p']) if a > b)
        print(f"Top10跑赢整池天数: {w}/{nd}")