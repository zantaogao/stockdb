#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影子复权评分（2026-09-24 建立；两台通用）

目的：不触碰生产推理路径（feat_tushare.apply_forward_adjust 仍是原样），
      用「真前复权」口径把当日全市场分数重算一遍，写入影子表，供与生产对照。

产出（写入 state.db / MacBook 的 signals.db）：
  1) ca_calendar  —— 全市场除权日历（adj_factor 跳变反推），供护栏/分析查询
  2) signal_shadow —— 当日全市场「现状 vs 真复权」两套分数与百分位

用法：
  python3 -B scripts/shadow_fuquan_score.py                # 最近交易日
  python3 -B scripts/shadow_fuquan_score.py 20260924       # 指定日
  python3 -B scripts/shadow_fuquan_score.py 20260924 --limit 300   # 快速自测

cron-window: 00:00-23:59   # 纯盘后计算，无时段限制（无需窗口保护）
"""
import sys, os, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path
import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / 'scripts'))

import duckdb
import feat_tushare as ft
import core.scoring as cs

ORIG_ADJ = ft.apply_forward_adjust


def apply_forward_adjust_v2(closes, highs, lows, adj_factors):
    """真·前复权：qfq[i] = raw[i] * f[i] / f[-1]

    调用方（core/scoring._compute_ml_features）传的是**全历史** adj_factor + 最近 N 根收盘，
    故此处按尾部对齐（adj_factor 逐日有行，尾部 n 个即最近 n 个交易日）。
    """
    fac = [float(f) for _, f in adj_factors if f is not None]
    n = len(closes)
    if not fac or n == 0:
        return closes, highs, lows
    tail = fac[-n:] if len(fac) >= n else ([fac[0]] * (n - len(fac)) + fac)
    base = tail[-1]
    if base <= 0:
        return closes, highs, lows
    return ([c * (f / base) for c, f in zip(closes, tail)],
            [h * (f / base) for h, f in zip(highs, tail)],
            [l * (f / base) for l, f in zip(lows, tail)])


def state_db_path():
    """M2 → state.db；MacBook（signal_history 在 signals.db）→ signals.db"""
    for name in ('signals.db', 'state.db'):
        p = BASE / name
        if not p.exists():
            continue
        try:
            c = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
            t = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signal_history'").fetchone()
            c.close()
            if t:
                return p
        except Exception:
            continue
    return BASE / 'state.db'


SDB = state_db_path()
TUSHARE = BASE / 'tushare.db'


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS ca_calendar (
        ts_code TEXT, ex_date TEXT, ratio REAL, fake_drop REAL, is_big INTEGER,
        created_at TEXT, PRIMARY KEY (ts_code, ex_date))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS signal_shadow (
        date TEXT, stock_code TEXT,
        fusion_cur REAL, fusion_adj REAL,
        reg20_cur REAL, reg20_adj REAL, reg40_cur REAL, reg40_adj REAL,
        pct_cur REAL, pct_adj REAL, final_score_cur REAL,
        is_ca INTEGER, ca_ratio REAL, ca_gap INTEGER,
        created_at TEXT, PRIMARY KEY (date, stock_code))""")
    conn.commit()


def update_ca_calendar(con_duck, conn, days=120, lag_days=200):
    """从 adj_factor 跳变反推除权事件（近 days 天，幂等 upsert）"""
    from datetime import timedelta
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=lag_days)).strftime('%Y%m%d')
    lim = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    rows = con_duck.execute(f"""
        WITH a AS (
          SELECT ts_code, trade_date, CAST(adj_factor AS DOUBLE) f,
                 lag(CAST(adj_factor AS DOUBLE)) OVER (PARTITION BY ts_code ORDER BY trade_date) pf
          FROM adj_factor WHERE trade_date >= '{start}'
        )
        SELECT ts_code, trade_date, f/pf, 1.0 - pf/f
        FROM a WHERE pf IS NOT NULL AND pf > 0 AND f/pf >= 1.0001 AND trade_date >= '{lim}'
    """).fetchall()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.executemany(
        "INSERT INTO ca_calendar(ts_code,ex_date,ratio,fake_drop,is_big,created_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(ts_code,ex_date) DO UPDATE SET ratio=excluded.ratio, fake_drop=excluded.fake_drop, "
        "is_big=excluded.is_big",
        [(ts, d, float(r), float(fd), 1 if r >= 1.05 else 0, now) for ts, d, r, fd in rows])
    conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('date', nargs='?', default=None)
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    t_start = time.time()
    con_duck = duckdb.connect(str(TUSHARE), read_only=True)
    con_duck.execute("SET memory_limit='2GB'; SET threads=2;")
    conn = sqlite3.connect(str(SDB), timeout=30)
    ensure_tables(conn)

    # ---- 1) 除权日历 ----
    n_cal = update_ca_calendar(con_duck, conn)
    print(f'[1/3] 除权日历：更新近 120 天事件 {n_cal} 条（累计 {conn.execute("SELECT COUNT(*) FROM ca_calendar").fetchone()[0]} 条）')

    # ---- 2) 目标日 + 池 ----
    D = args.date
    if not D:
        D = con_duck.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    pool = [r[0].split('.')[0][:6] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM signal_history WHERE REPLACE(date,'-','')=?", (D,)).fetchall()]
    pool = sorted(set(pool))
    if args.limit:
        pool = pool[:args.limit]
    print(f'[2/3] 目标日 {D}，评分池 {len(pool)} 只（signal_history）')
    if not pool:
        print('池为空，退出'); return

    # 交易日序列（判断除权后间隔用）
    dates_all = [r[0] for r in con_duck.execute(
        "SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260101' ORDER BY trade_date").fetchall()]
    di = {d: i for i, d in enumerate(dates_all)}
    ca = conn.execute("SELECT ts_code, ex_date, ratio FROM ca_calendar WHERE is_big=1").fetchall()
    ca_by_code = {}
    for ts, ex, ratio in ca:
        ca_by_code.setdefault(ts.split('.')[0][:6], []).append((ex, ratio))

    def ca_flag(code):
        """该票在 D 之前 20 个交易日内是否有除权 → (is_ca, ratio, gap)"""
        i = di.get(D)
        best = None
        for ex, ratio in ca_by_code.get(code, []):
            i0 = di.get(ex if len(str(ex)) == 8 else str(ex).replace('-', ''))
            if i is None or i0 is None:
                continue
            gap = i - i0
            if 0 <= gap <= 20 and (best is None or gap < best[2]):
                best = (1, ratio, gap)
        return best if best else (0, None, None)

    # ---- 3) 两口径评分 ----
    res = {}
    t0 = time.time()
    for i, code in enumerate(pool):
        ft.apply_forward_adjust = ORIG_ADJ
        A = cs.score_stock(code, conn=con_duck, as_of_date=D)
        ft.apply_forward_adjust = apply_forward_adjust_v2
        B = cs.score_stock(code, conn=con_duck, as_of_date=D)
        ft.apply_forward_adjust = ORIG_ADJ
        if A and B:
            res[code] = (A.get('fusion'), B.get('fusion'), A.get('reg_pred'), B.get('reg_pred'),
                         A.get('reg40_pred'), B.get('reg40_pred'))
        if (i + 1) % 500 == 0:
            print(f'    {i+1}/{len(pool)}  {time.time()-t0:.0f}s')
    print(f'    评分完成 {len(res)} 只，用时 {time.time()-t0:.0f}s')

    codes = list(res.keys())
    def pct(vals):
        v = np.array(vals); order = np.argsort(v)
        rk = np.empty(len(v), float); rk[order] = np.arange(1, len(v) + 1)
        return rk / len(v) * 100
    pc = pct([res[c][0] for c in codes])
    pa = pct([res[c][1] for c in codes])
    cur_score = {r[0].split('.')[0][:6]: r[1] for r in conn.execute(
        "SELECT stock_code, final_score FROM signal_history WHERE REPLACE(date,'-','')=?", (D,)).fetchall()}

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rows = []
    for i, c in enumerate(codes):
        f0, f1, r20c, r20a, r40c, r40a = res[c]
        is_ca, ratio, gap = ca_flag(c)
        rows.append((D, c, f0, f1, r20c, r20a, r40c, r40a, float(pc[i]), float(pa[i]),
                     cur_score.get(c), is_ca, ratio, gap, now))
    conn.executemany(
        "INSERT OR REPLACE INTO signal_shadow VALUES (" + ",".join("?" * 15) + ")", rows)
    conn.commit()

    # ---- 汇总 ----
    diffs = [r[8] - r[9] for r in rows]
    ev = [r for r in rows if r[11] == 1]
    print(f'[3/3] 写入 signal_shadow {len(rows)} 行 → {SDB.name}')
    print(f'  全市场百分位差(现状-真复权): 中位 {np.median(diffs):+.2f}  均值 {np.mean(diffs):+.2f}  >20分占比 {100*np.mean([d>20 for d in diffs]):.1f}%')
    if ev:
        print(f'  处于「除权后20日内」的票 {len(ev)} 只:')
        for r in sorted(ev, key=lambda x: -(x[8] - x[9]))[:15]:
            nm = con_duck.execute("SELECT name FROM stock_basic WHERE substr(ts_code,1,6)=? LIMIT 1", [r[1]]).fetchone()
            print(f'    {r[1]} {nm[0] if nm else "":8s} 假跌{(1-1/r[12]) if r[12] else 0:6.1%} '
                  f'现状%={r[8]:5.1f} 真复权%={r[9]:5.1f} 差 {r[8]-r[9]:+5.1f} (除权后第{r[13]}日)')
    top_c = sorted(rows, key=lambda x: -x[8])[:20]
    top_a = sorted(rows, key=lambda x: -x[9])[:20]
    print(f'  top20 重合 {len(set(x[1] for x in top_c) & set(x[1] for x in top_a))}/20')
    print(f'  用时合计 {time.time()-t_start:.0f}s')
    conn.close()
    con_duck.close()


if __name__ == '__main__':
    main()
