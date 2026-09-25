#!/usr/bin/env python3
"""影子链·IC 对拍：各影子 vs 生产 reg10/fusion
每个成熟信号日（信号日+10个交易日收益已齐）：
  同一股票集合上算各影子/reg10/fusion 的 10日前向收益 RankIC，写 ic_shadow 表（增量幂等）。
判定：对配对差做配对 t + Newey-West(lag10)（T+10 标签重叠修正），
换产标准：成熟日≥30 且 NW p<0.05 且 均值>0。
（影子B 09-21 退役：不再有新 B 分，ic_shadow_b 列仅存量历史值保留作证据；终裁见 retire 归档）
库口径：shadow_*_scores/ic_shadow/signal_history 在 signals.db(sqlite, date=YYYY-MM-DD)；
daily 在 tushare.db(duckdb, trade_date=YYYYMMDD)。
"""
import sys, sqlite3
import numpy as np, pandas as pd
from scipy import stats
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))
from core.db import get_tushare_db

FWD, NW_LAG = 10, 10
tcon = sqlite3.connect(BASE / 'signals.db')
tcon.execute("""CREATE TABLE IF NOT EXISTS ic_shadow (
    signal_date TEXT PRIMARY KEY,   -- YYYYMMDD
    n INTEGER, ic_shadow_b REAL, ic_reg10 REAL, ic_fusion REAL,
    computed_at TEXT DEFAULT (datetime('now','localtime')))""")
try:
    tcon.execute("ALTER TABLE ic_shadow ADD COLUMN ic_v4big REAL")
except sqlite3.OperationalError:
    pass  # 列已存在
try:
    tcon.execute("ALTER TABLE ic_shadow ADD COLUMN ic_v4d REAL")
except sqlite3.OperationalError:
    pass  # 列已存在
try:
    tcon.execute("ALTER TABLE ic_shadow ADD COLUMN ic_v4e REAL")
except sqlite3.OperationalError:
    pass  # 列已存在
try:
    tcon.execute("ALTER TABLE ic_shadow ADD COLUMN ic_clf10 REAL")
except sqlite3.OperationalError:
    pass  # 列已存在
try:
    tcon.execute("ALTER TABLE ic_shadow ADD COLUMN ic_v4f REAL")
except sqlite3.OperationalError:
    pass  # 列已存在

tconn = get_tushare_db()
all_days = [str(r[0]) for r in tconn.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
day_pos = {d: i for i, d in enumerate(all_days)}

def px_of(date_, tcodes):
    out = {}
    arr = list(tcodes)
    for k in range(0, len(arr), 900):
        ch = arr[k:k+900]
        ph = ','.join(['?'] * len(ch))
        for tc, c in tconn.execute(
                f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})",
                [date_] + ch).fetchall():
            out[str(tc)] = float(c)
    return out

shadow_days = sorted({str(r[0]) for r in tcon.execute(
    "SELECT DISTINCT date FROM shadow_v4big_scores").fetchall()} | {str(r[0]) for r in tcon.execute(
    "SELECT DISTINCT date FROM shadow_clf10_scores").fetchall()})
done_v4e_days = {r[0] for r in tcon.execute(
    "SELECT DISTINCT date FROM shadow_v4e_scores").fetchall()}
done = ({r[0] for r in tcon.execute("SELECT signal_date FROM ic_shadow WHERE ic_v4d IS NOT NULL").fetchall()}
        & (set(shadow_days) - done_v4e_days)
        | {r[0] for r in tcon.execute("SELECT signal_date FROM ic_shadow WHERE ic_v4e IS NOT NULL").fetchall()})
# clf10 腿独立增量：ic_clf10 已有值的日子若 shadow_clf10_scores 没新票也不用重算；
# 简单起见：ic_clf10 为 NULL 且该日有 clf10 分 → 必须重算，从 done 里剔除
_have_clf10_ic = {r[0] for r in tcon.execute(
    "SELECT signal_date FROM ic_shadow WHERE ic_clf10 IS NOT NULL").fetchall()}
done -= (set(shadow_days) - _have_clf10_ic)
# v4f 腿独立增量：ic_v4f 为 NULL 且该日确有 v4f 分 → 必须重算，从 done 里剔除
# （只看有分的日子；v4f 上线前的老日子不反复空转重算）
_have_v4f_ic = {r[0] for r in tcon.execute(
    "SELECT signal_date FROM ic_shadow WHERE ic_v4f IS NOT NULL").fetchall()}
_days_v4f = {r[0] for r in tcon.execute(
    "SELECT DISTINCT date FROM shadow_v4f_scores").fetchall()}
done -= (_days_v4f - _have_v4f_ic)

new_n = 0
for sd in shadow_days:
    if sd in done or sd not in day_pos or day_pos[sd] + FWD >= len(all_days):
        continue
    end = all_days[day_pos[sd] + FWD]
    sig = pd.read_sql_query(
        "SELECT stock_code AS code, reg10, fusion_score FROM signal_history WHERE date=?",
        tcon, params=(sd,)).drop_duplicates('code')
    if len(sig) < 100:
        continue
    m = sig.copy()
    codes = m['code'].astype(str).tolist()
    tcodes = [f"{c}.SH" if c.startswith(('6','68','9')) else f"{c}.SZ" for c in codes]
    p0d, p1d = px_of(sd, tcodes), px_of(end, tcodes)
    p0 = np.array([p0d.get(t, np.nan) for t in tcodes], dtype=float)
    p1 = np.array([p1d.get(t, np.nan) for t in tcodes], dtype=float)
    ok = np.isfinite(p0) & np.isfinite(p1) & (p0 > 0) & (p1 > 0)
    if ok.sum() < 100:
        continue
    ret = p1[ok] / p0[ok] - 1
    ret_all = np.full(len(m), np.nan); ret_all[ok] = ret
    ic_10 = stats.spearmanr(m['reg10'].astype(float).to_numpy()[ok], ret)[0]
    ic_fu = stats.spearmanr(m['fusion_score'].astype(float).to_numpy()[ok], ret)[0]
    # v4_big 影子 IC（同一股票集合同一收益口径；map 对齐避免 merge 行序错位）
    v4map = dict(tcon.execute("SELECT code, score FROM shadow_v4big_scores WHERE date=?", (sd,)).fetchall())
    s4 = m['code'].map(v4map).to_numpy(dtype=float)
    d4map = dict(tcon.execute("SELECT code, score FROM shadow_v4d_scores WHERE date=?", (sd,)).fetchall())
    s4d = m['code'].map(d4map).to_numpy(dtype=float)
    okv = ok & np.isfinite(s4)
    ic_v4 = stats.spearmanr(s4[okv], ret_all[okv])[0] if okv.sum() >= 100 else None
    okd = ok & np.isfinite(s4d)
    ic_4d = stats.spearmanr(s4d[okd], ret_all[okd])[0] if okd.sum() >= 100 else None
    # v4e 影子 IC（同一股票集合同一收益口径）
    e4map = dict(tcon.execute("SELECT code, score FROM shadow_v4e_scores WHERE date=?", (sd,)).fetchall())
    s4e = m['code'].map(e4map).to_numpy(dtype=float)
    oke = ok & np.isfinite(s4e)
    ic_4e = stats.spearmanr(s4e[oke], ret_all[oke])[0] if oke.sum() >= 100 else None
    # clf10 影子 IC（binary概率分数，同一票池同一收益口径）
    f10map = dict(tcon.execute("SELECT code, score FROM shadow_clf10_scores WHERE date=?", (sd,)).fetchall())
    sf10 = m['code'].map(f10map).to_numpy(dtype=float)
    okf = ok & np.isfinite(sf10)
    ic_f10 = stats.spearmanr(sf10[okf], ret_all[okf])[0] if okf.sum() >= 100 else None
    # v4f 影子 IC（38维=36+日频微观kyle/amihud，同一票池同一收益口径）
    f4map = dict(tcon.execute("SELECT code, score FROM shadow_v4f_scores WHERE date=?", (sd,)).fetchall())
    sv4f = m['code'].map(f4map).to_numpy(dtype=float)
    okv4f = ok & np.isfinite(sv4f)
    ic_v4f = stats.spearmanr(sv4f[okv4f], ret_all[okv4f])[0] if okv4f.sum() >= 100 else None
    # ic_shadow_b 透传存量（B 09-21 退役不再新算；重算日防止 INSERT OR REPLACE 抹历史值）
    prev_b = tcon.execute("SELECT ic_shadow_b FROM ic_shadow WHERE signal_date=?", (sd,)).fetchone()
    prev_b = prev_b[0] if prev_b else None
    tcon.execute(
        "INSERT OR REPLACE INTO ic_shadow(signal_date,n,ic_shadow_b,ic_reg10,ic_fusion,ic_v4big,ic_v4d,ic_v4e,ic_clf10,ic_v4f) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sd, int(ok.sum()), prev_b,  # B 退役：恒透传存量（新建行=NULL）
         round(float(ic_10), 6), round(float(ic_fu), 6),
         round(float(ic_v4), 6) if ic_v4 is not None and np.isfinite(ic_v4) else None,
         round(float(ic_4d), 6) if ic_4d is not None and np.isfinite(ic_4d) else None,
         round(float(ic_4e), 6) if ic_4e is not None and np.isfinite(ic_4e) else None,
         round(float(ic_f10), 6) if ic_f10 is not None and np.isfinite(ic_f10) else None,
         round(float(ic_v4f), 6) if ic_v4f is not None and np.isfinite(ic_v4f) else None))
    new_n += 1
tcon.commit()

hist = pd.read_sql_query("SELECT * FROM ic_shadow ORDER BY signal_date", tcon)
print(f"新增成熟日 {new_n}，累计 {len(hist)} 个成熟影子日")
if len(hist):
    print(hist[['signal_date','n','ic_shadow_b','ic_reg10','ic_fusion','ic_v4big','ic_v4d','ic_clf10','ic_v4f']].tail(5).to_string(index=False))

def nw_test(d, tag):
    n = len(d)
    e = d - d.mean()
    var = (e @ e) / n
    for lag in range(1, NW_LAG + 1):
        w = 1 - lag / (NW_LAG + 1)
        var += 2 * w * (e[lag:] @ e[:-lag]) / n
    se_nw = np.sqrt(var / n)
    t_nw = d.mean() / se_nw if se_nw > 0 else 0.0
    p_nw = 2 * (1 - stats.norm.cdf(abs(t_nw)))
    t_naive, p_naive = stats.ttest_1samp(d, 0)
    print(f"{tag} 均值 {d.mean():+.4f} | 朴素 t={t_naive:+.2f} p={p_naive:.4f} | "
          f"NW(lag{NW_LAG}) t={t_nw:+.2f} p={p_nw:.4f} | 成熟日 {n}")
    if n >= 30:
        verdict = '✅ 达到换产标准' if (p_nw < 0.05 and d.mean() > 0) else '❌ 未达标，继续影子观察'
        print(f"判定({n}天): {verdict}")
    else:
        print(f"观察中：还需约 {30-n} 个成熟日")

# B 腿 09-21 退役，不再做判定（历史终裁：前19日 B-reg10 均值差 -0.0388，见 retire 归档）
hv = hist.dropna(subset=['ic_v4big'])
if len(hv) >= 5:
    nw_test((hv['ic_v4big'] - hv['ic_reg10']).to_numpy(), 'v4big-reg10')
hd = hist.dropna(subset=['ic_v4d'])
if len(hd) >= 5:
    nw_test((hd['ic_v4d'] - hv['ic_v4big'].reindex(hd.index)).to_numpy(), 'v4d-v4big')
hf = hist.dropna(subset=['ic_clf10'])
if len(hf) >= 5:
    nw_test((hf['ic_clf10'] - hf['ic_reg10']).to_numpy(), 'clf10-reg10(生产)')
# v4f 判定腿：与 v4d 同票池配对（38维 vs 36维，差的正是 kyle/amihud 两维），
# 换产标准：成熟日≥30 且 NW p<0.05 且均值>0
h4f = hist.dropna(subset=['ic_v4f', 'ic_v4d'])
if len(h4f) >= 5:
    nw_test((h4f['ic_v4f'] - h4f['ic_v4d']).to_numpy(), 'v4f-v4d')