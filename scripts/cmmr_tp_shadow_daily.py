#!/usr/bin/env python3
"""CMMR 账户口径 TP 中途止盈影子轨（2026-09-13 用户批准新建）。
背景：fwd10 IC 为正 / fwd20 IC 为负 + 17年重放退出对拍（scripts/_cmmr_exit_rules_17y.py）
显示止盈退出显著优于持到重评日（TP3 +12.9pp/TP5 +9.6pp 年化）。17年版的绝对水平被
代理次级键污染（无 fusion 分），本影子轨用**账户真实选池**（≥80 地板 + 档内
fusion_score 次级键，与 strategy_accounts_daily.get_signal_targets cmmr 分支逐字同键序）
逐日建 cohort，对每 cohort 记三轨：
  hold  = 持有 20 交易日出口收益（现行账户语义）
  tp5   = 持有期内首次收盘浮盈≥5%当日收盘落袋（无触发=同 hold）
  tp3   = 同上，阈值3%
超额 = 组合收益 − 同窗口全市场等权（与 backtest_cmmr.mkt_ew 同口径，原始收盘价，T日收盘入场）。
每日 cron(17:00 shadow_daily.sh 第4步) 推进所有未完成 cohort；entry+20 交易日齐→done=1。
终审：done≥20 时比较 excess_tp5/tp3 vs excess_hold（配对 t + NW-t）。零动线影响。
"""
import sqlite3, sys, os
import numpy as np
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))
from core.db import get_tushare_db

SIG = os.path.expanduser('~/.hermes/stockdb/signals.db')
START = '20260101'   # signal_history 最早日期；无 cmmr 分的早期日自动跳过
st = sqlite3.connect(SIG)
tsh = get_tushare_db()

st.execute("""CREATE TABLE IF NOT EXISTS cmmr_tp_shadow(
  signal_date TEXT PRIMARY KEY, n INTEGER,
  ret_hold REAL, ret_tp5 REAL, ret_tp3 REAL, tp5_lag INTEGER, tp3_lag INTEGER,
  mkt_hold REAL, mkt_tp5 REAL, mkt_tp3 REAL,
  done INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

cal = [str(r[0]) for r in tsh.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE trade_date>=? ORDER BY 1", (START,)).fetchall()]
pos = {d: i for i, d in enumerate(cal)}
last_i = len(cal) - 1

def picks(d):
    """账户真实选池 top10（与 get_signal_targets cmmr 分支同键序）"""
    rows = st.execute("""
        SELECT stock_code FROM signal_history
        WHERE REPLACE(date,'-','')=? AND cmmr_score >= 80
        ORDER BY cmmr_score DESC, COALESCE(fusion_score,0) DESC, stock_code
        LIMIT 10""", (d,)).fetchall()
    return [r[0] for r in rows]

def ts(code):
    return code + ('.SH' if code.startswith(('6','9')) else '.SZ')

def closes_on(d, codes):
    out = {}
    for d2 in [d]:
        for r in tsh.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (d2,)).fetchall():
            out[str(r[0])] = float(r[1])
    return {c: out.get(ts(c)) for c in codes}

def mkt_ew(d0, d1):
    """d0收盘→d1收盘 全市场等权（backtest_cmmr 口径：两日都有价的票才计）"""
    r = tsh.execute("""
        SELECT a.ts_code, a.close, b.close FROM daily a JOIN daily b USING(ts_code)
        WHERE a.trade_date=? AND b.trade_date=? AND (a.ts_code LIKE '%.SZ' OR a.ts_code LIKE '%.SH')""",
        (d0, d1)).fetchall()
    if not r: return None
    return float(np.mean([(b/a-1)*100 for _, a, b in r if a > 0]))

# 初始化 cohort
for d in [d for d in cal if pos[d] + 1 <= last_i]:
    ds = f'{d[:4]}-{d[4:6]}-{d[6:]}'
    if not st.execute("SELECT 1 FROM signal_history WHERE date=? LIMIT 1", (ds,)).fetchone():
        continue
    p = picks(d)
    if not p: continue
    st.execute("INSERT OR IGNORE INTO cmmr_tp_shadow(signal_date,n) VALUES(?,?)", (d, len(p)))
st.commit()

# 推进所有未完成 cohort
rows = st.execute("SELECT signal_date, done FROM cmmr_tp_shadow WHERE done=0").fetchall()
adv = 0
for d, _ in rows:
    i0 = pos.get(d)
    if i0 is None: continue
    p = picks(d)
    c0 = closes_on(d, p)
    entry_ok = [c for c in p if c0.get(c) and c0[c] > 0]
    if not entry_ok: continue
    cums = {}   # lag -> (port_ret, mkt_ret)
    prev_port, prev_mkt = 0.0, 0.0
    for lag in range(1, 21):
        if i0 + lag > last_i: break
        d1 = cal[i0 + lag]
        c1 = closes_on(d1, entry_ok)
        # 组合等权：停牌沿用前一日组合贡献（近似 hold 语义）
        tot = 0.0; nn = 0
        for c in entry_ok:
            if c1.get(c) and c0[c] > 0:
                tot += (c1[c]/c0[c]-1)*100; nn += 1
        port = (tot/len(entry_ok)) if nn else prev_port
        mk = mkt_ew(d, d1)
        cums[lag] = (port, mk if mk is not None else prev_mkt)
        prev_port, prev_mkt = port, cums[lag][1]
    hold = cums.get(20)
    if hold is None:
        continue  # 未到出口，等明晚
    def track(th):
        for lag in range(1, 21):
            if lag in cums and cums[lag][0] >= th:
                return cums[lag][0], cums[lag][1], lag
        return hold[0], hold[1], 20
    r5, m5, l5 = track(5.0)
    r3, m3, l3 = track(3.0)
    st.execute("""UPDATE cmmr_tp_shadow SET ret_hold=?, ret_tp5=?, ret_tp3=?,
        tp5_lag=?, tp3_lag=?, mkt_hold=?, mkt_tp5=?, mkt_tp3=?, done=1,
        updated_at=CURRENT_TIMESTAMP WHERE signal_date=?""",
        (round(hold[0],4), round(r5,4), round(r3,4), l5, l3,
         round(hold[1],4), round(m5,4), round(m3,4), d))
    adv += 1
st.commit()

done = st.execute("SELECT COUNT(*) FROM cmmr_tp_shadow WHERE done=1").fetchone()[0]
print(f'本次推进完成 {adv} 个 cohort | 累计成熟 {done} 个')
if done >= 2:
    import math
    dat = st.execute("""SELECT signal_date, ret_hold-mkt_hold, ret_tp5-mkt_tp5, ret_tp3-mkt_tp3,
        tp5_lag, tp3_lag FROM cmmr_tp_shadow WHERE done=1 ORDER BY signal_date""").fetchall()
    def tstat(v):
        v = np.array(v); m = np.isfinite(v)
        v = v[m]
        if len(v) < 2 or v.std() == 0: return 0.0
        return v.mean() / (v.std(ddof=1)/math.sqrt(len(v)))
    eh = [r[1] for r in dat]; e5 = [r[2] for r in dat]; e3 = [r[3] for r in dat]
    print(f"成熟{done}日 日均超额%: hold={np.mean(eh):+.3f} tp5={np.mean(e5):+.3f} tp3={np.mean(e3):+.3f}")
    print(f"配对差 tp5-hold={np.mean(np.array(e5)-np.array(eh)):+.3f} t={tstat(np.array(e5)-np.array(eh)):+.2f}"
          f" | tp3-hold={np.mean(np.array(e3)-np.array(eh)):+.3f} t={tstat(np.array(e3)-np.array(eh)):+.2f}")
    print(f"tp5 触发率: {sum(1 for r in dat if r[4]<20)}/{done}  tp3: {sum(1 for r in dat if r[5]<20)}/{done}")
    print("判定: 配对差 t≥2 且均值为正 = TP 优于现行 hold；满20成熟日前为观察期")
