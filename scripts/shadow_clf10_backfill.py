#!/usr/bin/env python3
"""clf10 影子·历史回补：给 signal_history 覆盖但 shadow_clf10_scores 缺的日期批量打分。
与 shadow_score_daily.py 的 clf10 腿逐字同口径（同 compute_features、同 PV_INDICES、
同前复权、同指数dict、同 stats_clf10.json 标准化），差异仅两处并记录在案：
  1) 不做 tdx 覆盖过滤（clf10 不吃日内特征；IC 对拍时 ic_shadow 自动与 signal_history 取交集）
  2) 按票一次拉全窗口再逐日切窗，代替按日拉取（快）
幂等：已有分数的日期跳过。跑完由 shadow_ic_check.py 统一算成熟日 IC。
"""
import sys, json, sqlite3, time
import numpy as np, pandas as pd
import lightgbm as lgb
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE / 'scripts')); sys.path.insert(0, str(BASE))
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data
from core.db import get_tushare_db

FEAT_WIN = 60
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]

if __name__ == '__main__':
    t0 = time.time()
    clfstats = json.loads((BASE / 'models/shadow_clf10/stats_clf10.json').read_text())
    modelf10 = lgb.Booster(model_file=str(BASE / 'models/shadow_clf10/lgb_clf_10d.txt'))

    tcon = sqlite3.connect(BASE / 'signals.db')
    tcon.execute("""CREATE TABLE IF NOT EXISTS shadow_clf10_scores (
        date TEXT, code TEXT, score REAL,
        PRIMARY KEY (date, code))""")
    have = {str(r[0]) for r in tcon.execute("SELECT DISTINCT date FROM shadow_clf10_scores").fetchall()}
    targets = [str(r[0]) for r in tcon.execute(
        "SELECT DISTINCT date FROM signal_history ORDER BY date").fetchall()
        if str(r[0]) not in have]
    if not targets:
        print("无缺口，跳过"); sys.exit(0)
    tset = {t[:10] for t in targets}
    print(f"回补 {len(targets)} 天: {targets[0]} ~ {targets[-1]}", flush=True)

    conn = get_tushare_db()
    idx_data = load_index_data()
    stocks = [r[0] for r in conn.execute(
        "SELECT symbol, name FROM stock_basic WHERE market != '北交所'").fetchall()
        if not any(s in (r[1] or '') for s in ('ST','st','退'))
        and not r[0].startswith(('8','4','92'))]
    cut = '20260301'   # 最早目标日20260724前留足61交易日窗
    rows_all, codes_all, dates_all = [], [], []
    done = 0
    for code in stocks:
        done += 1
        if done % 500 == 0:
            print(f"  {done}/{len(stocks)} 耗时{time.time()-t0:.0f}s", flush=True)
        ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
        dfr = conn.execute(
            "SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol FROM daily "
            f"WHERE ts_code='{ts_code}' AND trade_date >= '{cut}' ORDER BY trade_date").fetchall()
        if not dfr:
            continue
        closes = [float(r[1]) for r in dfr]; highs = [float(r[2]) for r in dfr]
        lows = [float(r[3]) for r in dfr]
        pcts = [float(r[4])/100.0 for r in dfr]; vols = [float(r[5]) for r in dfr]
        dates = [str(r[0])[:10] for r in dfr]
        dset = set(dates)
        hit = [d for d in tset if d in dset]
        if not hit:
            continue
        adj_rows = conn.execute(
            "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",
            [ts_code]).fetchall()
        ac, ah, al = apply_forward_adjust(closes, highs, lows, adj_rows)
        idx_info = idx_data.get(get_board_index(code))
        for d in hit:
            i = dates.index(d)
            if i < FEAT_WIN:
                continue
            sl = slice(i - FEAT_WIN, i + 1)   # 61点窗，终点=d（与训练 [i-60,i] 对齐）
            idx_dict = None
            if idx_info and d in idx_info.get('dict', {}):
                idx_dict = {k: v for k, v in idx_info['dict'].items() if k <= d}
            f38 = compute_features(ac[sl], ah[sl], al[sl], vols[sl], pcts[sl], idx_dict,
                                   {'ep':0.5,'bp':0.5,'ln_cap':22.0})
            base = f38 if isinstance(f38, list) else list(f38)
            rows_all.append([base[j] for j in PV_INDICES])
            codes_all.append((d.replace('-',''), code))
    X = np.array(rows_all, dtype=np.float64)
    for j in range(31):
        st = clfstats[f'feat_{j}']
        sd = st['std'] if st['std'] > 0 else 1.0
        X[:, j] = (np.clip(X[:, j], st['low'], st['high']) - st['mean']) / sd
    X = np.nan_to_num(X, nan=0.0)
    pred = modelf10.predict(X)
    tcon.executemany("INSERT OR REPLACE INTO shadow_clf10_scores VALUES (?,?,?)",
                     [(d, c, float(p)) for (d, c), p in zip(codes_all, pred)])
    tcon.commit()
    got = tcon.execute("SELECT COUNT(DISTINCT date) FROM shadow_clf10_scores").fetchone()[0]
    print(f"回补完成 {len(pred):,} 条打分，覆盖 {got} 天（含新增{len(targets)}），耗时{time.time()-t0:.0f}s")
