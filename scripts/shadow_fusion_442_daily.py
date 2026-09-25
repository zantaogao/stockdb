#!/usr/bin/env python3
"""40/40/20 三模型融合影子监控（2026-09-06 用户拍板新建；09-10 增加两条隔离腿）。
候选权重: reg10:reg20:reg40 = 40:40:20（原用 v4_big 当 10d 腿）。
对照基准: 生产 fusion_score = round(0.20*reg10 + 0.30*reg20 + 0.50*reg40, 1)
          （实测 rho=0.9999、平均偏差 0.014 分；写成 "0.7*reg40+0.3*reg20" 只是忽略
           reg10 项后的近似式，rho 0.9968、平均偏差 0.91 分，勿当严格口径——reg40 权重是 50% 不是 70%）
四个变体防尺度陷阱（前两个用 v4_big 当 10d 腿，后两个用生产 reg10 v3）:
  s_clip:    三路都按生产映射（v4big*100 化百分点）线性加权 → 10d 腿幅值仍偏小
  s_z:       三路各自当日截面 z 标准化再加权（幅值公平）
  s_442_v3:  同 s_z 的 40/40/20，但 10d 腿换成生产 reg10 v3 → 隔离"换 10d 模型"与"换权重/映射"两个变量
  s_prod_z:  生产权重 20/30/50 + z 归一化 → 只修量纲、不动权重（"口径修复但不调参"的对照）
  s_r10:     纯生产 reg10 v3 单腿（Top10 口径下三窗口实测最强，压测上限用）
  s_r10r20:  生产 reg10 v3 与 reg20 的 z 等权(0.5/0.5)＝短窗口双榜、不掺 reg40
             （2026-09-11 新增这两腿：M2 侧 19/9/28 天三窗口复算显示 442 在 IC 与 Top10
              两个口径都不占优——IC 劣于生产、Top10 劣于纯 reg10 / reg10+reg20）
每日: 对已成熟(信号日+10交易日)的日期算 Spearman IC + Top10/Bot10 等权10d超额（减当日中位数），
写 signals.db ic_shadow_442，打印累计 NW-t 报告 + 换产判定。cron 每个交易日 17:00（shadow_daily.sh 第 3 步）。
⚠️ top10_*/bot10_* 列存的是**超额**（组合收益 − 当日中位数收益），mkt10 存当日中位数本身备核。"""
import sqlite3, sys, time as _t
import numpy as np, pandas as pd
from scipy import stats as sps

DB = '/Users/zantao/.hermes/stockdb/signals.db'
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.db import get_tushare_db
W_10D, W_20D, W_40D = 0.4, 0.4, 0.2
FWD = 10
START = '20260806'          # v4big 影子起算日（08-05 起有分）
_t0 = _t.time()

st = sqlite3.connect(DB)
tsh = get_tushare_db()

cal = [str(r[0]) for r in tsh.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
day_pos = {d: i for i, d in enumerate(cal)}

def px_of(date_, tcodes):
    out = {}
    arr = list(tcodes)
    for k in range(0, len(arr), 900):
        ch = arr[k:k+900]
        ph = ','.join(['?'] * len(ch))
        for tc, c in tsh.execute(
                f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})",
                [date_] + ch).fetchall():
            out[str(tc)] = float(c)
    return out

sig_days = [str(r[0]) for r in st.execute(
    "SELECT DISTINCT replace(date,'-','') FROM signal_history WHERE replace(date,'-','')>=? ORDER BY 1",
    (START,)).fetchall()]
have_v4 = {str(r[0]) for r in st.execute(
    "SELECT DISTINCT date FROM shadow_v4big_scores").fetchall()}

st.execute("""CREATE TABLE IF NOT EXISTS ic_shadow_442(
  signal_date TEXT PRIMARY KEY, n INTEGER,
  ic_442_clip REAL, ic_442_z REAL, ic_fusion REAL, ic_v4big REAL,
  top10_442_clip REAL, top10_442_z REAL, top10_fusion REAL, bot10_fusion REAL,
  ic_442_v3 REAL, ic_prod_z REAL, top10_442_v3 REAL, top10_prod_z REAL,
  bot10_442_z REAL, bot10_442_v3 REAL, bot10_prod_z REAL, mkt10 REAL,
  ic_r10 REAL, ic_r10r20 REAL, top10_r10 REAL, top10_r10r20 REAL,
  bot10_r10 REAL, bot10_r10r20 REAL)""")
# 老库补列（幂等，2026-09-10 加两条隔离腿；2026-09-11 加短窗口两条腿）
for _c in ('ic_442_v3', 'ic_prod_z', 'top10_442_v3', 'top10_prod_z',
           'bot10_442_z', 'bot10_442_v3', 'bot10_prod_z', 'mkt10',
           'ic_r10', 'ic_r10r20', 'top10_r10', 'top10_r10r20',
           'bot10_r10', 'bot10_r10r20'):
    try:
        st.execute(f"ALTER TABLE ic_shadow_442 ADD COLUMN {_c} REAL")
    except sqlite3.OperationalError:
        pass
IC_COLS = ['signal_date', 'n', 'ic_442_clip', 'ic_442_z', 'ic_fusion', 'ic_v4big',
           'top10_442_clip', 'top10_442_z', 'top10_fusion', 'bot10_fusion',
           'ic_442_v3', 'ic_prod_z', 'top10_442_v3', 'top10_prod_z',
           'bot10_442_z', 'bot10_442_v3', 'bot10_prod_z', 'mkt10',
           'ic_r10', 'ic_r10r20', 'top10_r10', 'top10_r10r20',
           'bot10_r10', 'bot10_r10r20']

# 全量重算（单日1s级，INSERT OR REPLACE幂等）：改权重后旧行自动被覆盖，无需手工清表
done = set()
new_n = 0
for sd in sig_days:
    if sd in done or sd not in have_v4 or sd not in day_pos or day_pos[sd] + FWD >= len(cal):
        continue
    end = cal[day_pos[sd] + FWD]
    d = pd.read_sql_query(
        """SELECT replace(s.date,'-','') d, s.stock_code code, s.stock_name name,
                  s.reg10, s.reg20, s.reg40, s.fusion_score, v.score v4big
           FROM signal_history s
           JOIN shadow_v4big_scores v
             ON v.code=s.stock_code AND replace(v.date,'-','')=replace(s.date,'-','')
           WHERE replace(s.date,'-','')=?""", st, params=(sd,))
    d = d[~d['name'].str.contains('ST|退', na=False)]
    d = d[~d['code'].str.startswith(('8', '4', '9'))]
    d = d.dropna(subset=['reg10', 'reg20', 'reg40', 'v4big', 'fusion_score'])
    d = d.drop_duplicates('code')
    if len(d) < 100:
        continue
    # 变体1: 生产同构线性加权（原始百分点单位）。单位修正(09-06复查):
    #   reg20/reg40 列=百分点原始预测（生产fusion_score=0.7*reg40+0.3*reg20 直接线性，rho0.9948实锤）;
    #   reg10/v4big 列=十进制小数（0.086=8.6%），必须*100 化百分点再进公式，否则40%权重退化为常数50.2分
    d['s_clip'] = W_10D * (d['v4big'] * 100) + W_20D * d['reg20'] + W_40D * d['reg40']
    # 变体2: 当日截面z标准化（幅值公平）
    def z(c): return (d[c] - d[c].mean()) / (d[c].std() or 1)
    d['s_z'] = W_10D * z('v4big') + W_20D * z('reg20') + W_40D * z('reg40')
    # 变体3: 40/40/20 + z，10d 腿用生产 reg10 v3（隔离"换 10d 模型"变量；z 无量纲故 reg10 小数口径无碍）
    d['s_442_v3'] = W_10D * z('reg10') + W_20D * z('reg20') + W_40D * z('reg40')
    # 变体4: 生产权重 20/30/50 + z（只修量纲、不动权重）
    d['s_prod_z'] = 0.20 * z('reg10') + 0.30 * z('reg20') + 0.50 * z('reg40')
    # 变体5/6（2026-09-11）: 短窗口两条腿——纯 10d 单腿、10d+20d z 等权（不掺 reg40）
    d['s_r10'] = d['reg10']                                  # 单腿，排序即 reg10 排序
    d['s_r10r20'] = 0.5 * z('reg10') + 0.5 * z('reg20')

    codes = d['code'].astype(str).tolist()
    tcodes = [f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ" for c in codes]
    p0d, p1d = px_of(sd, tcodes), px_of(end, tcodes)
    p0 = np.array([p0d.get(t, np.nan) for t in tcodes], dtype=float)
    p1 = np.array([p1d.get(t, np.nan) for t in tcodes], dtype=float)
    ok = np.isfinite(p0) & np.isfinite(p1) & (p0 > 0) & (p1 > 0)
    if ok.sum() < 100:
        continue
    ret = p1[ok] / p0[ok] - 1
    mkt = float(np.median(ret))

    def top_bot(col):
        v = d[col].to_numpy()[ok]
        idx = np.argsort(-v)
        top = float(np.mean(ret[idx[:10]]))
        bot = float(np.mean(ret[idx[-10:]]))
        return top, bot
    tc, bc = top_bot('s_clip')
    tz, bz = top_bot('s_z')
    tf, bf = top_bot('fusion_score')
    t3, b3 = top_bot('s_442_v3')
    tp, bp = top_bot('s_prod_z')
    tR, bR = top_bot('s_r10')
    tRR, bRR = top_bot('s_r10r20')
    _ic = lambda c: round(float(sps.spearmanr(d[c].to_numpy()[ok], ret)[0]), 6)
    # ⚠️ 2026-09-11 修：原按位置 VALUES 在新增列后错位（mkt10 写到了最后）→ 改按列名赋值，杜绝列序坑
    _row = {
        'signal_date': sd, 'n': int(ok.sum()),
        'ic_442_clip': _ic('s_clip'), 'ic_442_z': _ic('s_z'),
        'ic_fusion': _ic('fusion_score'), 'ic_v4big': _ic('v4big'),
        'top10_442_clip': round(tc - mkt, 5), 'top10_442_z': round(tz - mkt, 5),
        'top10_fusion': round(tf - mkt, 5), 'bot10_fusion': round(bf - mkt, 5),
        'ic_442_v3': _ic('s_442_v3'), 'ic_prod_z': _ic('s_prod_z'),
        'top10_442_v3': round(t3 - mkt, 5), 'top10_prod_z': round(tp - mkt, 5),
        'bot10_442_z': round(bz - mkt, 5), 'bot10_442_v3': round(b3 - mkt, 5),
        'bot10_prod_z': round(bp - mkt, 5), 'mkt10': round(mkt, 5),
        'ic_r10': _ic('s_r10'), 'ic_r10r20': _ic('s_r10r20'),
        'top10_r10': round(tR - mkt, 5), 'top10_r10r20': round(tRR - mkt, 5),
        'bot10_r10': round(bR - mkt, 5), 'bot10_r10r20': round(bRR - mkt, 5),
    }
    st.execute(f"INSERT OR REPLACE INTO ic_shadow_442 ({','.join(_row)}) "
               f"VALUES ({','.join(':' + k for k in _row)})", _row)
    new_n += 1
st.commit()

hist = pd.read_sql_query("SELECT * FROM ic_shadow_442 ORDER BY signal_date", st)
print(f"442影子对拍 | 新成熟{new_n} 累计成熟{len(hist)}日 | 窗口 {hist['signal_date'].min()}~{hist['signal_date'].max()}" if len(hist) else "暂无成熟日")

def nw(d, tag):
    s = d.dropna()
    n = len(s)
    if n < 5:
        print(f"  {tag:<12} n={n} 样本不足"); return
    m = s.mean(); sd_ = s.std()
    g = 5
    nwv = sd_**2 / n
    for l in range(1, g + 1):
        c = ((s - m).shift(l) * (s - m)).mean()
        if pd.notna(c): nwv += 2 * (1 - l / (g + 1)) * c
    se = np.sqrt(nwv) if nwv > 0 else sd_ / np.sqrt(n)  # NW方差可能非正，回退朴素SE
    print(f"  {tag:<12} n={n} 均值{m:+.4f} 朴素t{m/(sd_/np.sqrt(n)):+.2f} NW-t{m/se:+.2f} 胜率{(s>0).mean()*100:.0f}%")

if len(hist):
    print("== 10d前瞻 Spearman IC（全市场截面，剔ST/北交所）")
    for c, tag in [('ic_442_clip', '442-clip(v4big)'), ('ic_442_z', '442-z(v4big)'),
                   ('ic_442_v3', '442-z(reg10v3)'), ('ic_prod_z', 'prod-z(20/30/50)'),
                   ('ic_r10', 'r10单腿'), ('ic_r10r20', 'r10+r20 z等权'),
                   ('ic_fusion', '生产fusion'), ('ic_v4big', 'v4big单独')]:
        nw(hist[c], tag)
    print("== Top10等权10d超额（vs当日中位）")
    for c, tag in [('top10_442_clip', '442-clip(v4big)'), ('top10_442_z', '442-z(v4big)'),
                   ('top10_442_v3', '442-z(reg10v3)'), ('top10_prod_z', 'prod-z(20/30/50)'),
                   ('top10_r10', 'r10单腿'), ('top10_r10r20', 'r10+r20 z等权'),
                   ('top10_fusion', '生产fusion')]:
        s = hist[c].dropna()
        if len(s):
            print(f"  {tag:<18} 均值{s.mean()*100:+.2f}%/10d 跑赢市场{(s>0).mean()*100:.0f}%天")
    print("== 换产判定（与生产fusion 逐日配对差；标准: 成熟日≥30 且 NW-t≥2 且 均值>0）")

    def judge(col, base, tag, thr=30):
        s = (hist[col] - hist[base]).dropna()
        n = len(s)
        if n < 5:
            print(f"  {tag:<26} n={n} 样本不足"); return
        m = s.mean(); sd = s.std()
        g, nwv = 5, s.std() ** 2 / n
        for l in range(1, g + 1):
            cc = ((s - m).shift(l) * (s - m)).mean()
            if pd.notna(cc):
                nwv += 2 * (1 - l / (g + 1)) * cc
        se = np.sqrt(nwv) if nwv > 0 else sd / np.sqrt(n)
        t = m / se
        bad = (n >= thr and t >= 2 and m > 0)
        print(f"  {tag:<26} n={n} 均值差{m:+.4f} NW-t{t:+.2f} {'✅达到换产标准' if bad else '❌未达标'}")

    print("  [IC 口径 = 全市场排序]")
    for c, tag in [('ic_442_clip', 'IC 442-clip(v4big)'), ('ic_442_z', 'IC 442-z(v4big)'),
                   ('ic_442_v3', 'IC 442-z(reg10v3)'), ('ic_prod_z', 'IC prod-z(20/30/50)'),
                   ('ic_r10', 'IC r10单腿            '), ('ic_r10r20', 'IC r10+r20 z等权     ')]:
        judge(c, 'ic_fusion', tag)
    print("  [Top10口径 = 主账户实际买入粒度]")
    for c, tag in [('top10_442_clip', 'Top10 442-clip(v4big)'), ('top10_442_z', 'Top10 442-z(v4big)'),
                   ('top10_442_v3', 'Top10 442-z(reg10v3)'), ('top10_prod_z', 'Top10 prod-z(20/30/50)'),
                   ('top10_r10', 'Top10 r10单腿        '), ('top10_r10r20', 'Top10 r10+r20 z等权   ')]:
        judge(c, 'top10_fusion', tag)
    print(hist.tail(5)[['signal_date', 'n', 'ic_442_clip', 'ic_442_z', 'ic_442_v3', 'ic_prod_z',
                        'ic_r10', 'ic_r10r20', 'ic_fusion',
                        'top10_fusion', 'top10_442_v3', 'top10_prod_z',
                        'top10_r10', 'top10_r10r20']].to_string(index=False))
print(f"耗时 {_t.time()-_t0:.0f}s")