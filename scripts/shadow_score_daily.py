#!/usr/bin/env python3
"""影子链·每日打分：给最新交易日打分，写 signals.db shadow_v4big/v4d/v4e/clf10/v4f_scores
（影子B 已于 2026-09-21 退役：30成熟日终裁前 19 日 B-reg10 均值差 -0.0388，归档 retire/shadow_b_retired_20260921.tar.gz）
管线与 ab_build_samples.py 逐字一致（同 compute_features、同 PV_INDICES、同前复权、同指数dict），
各模型标准化用各自训练随附 stats（口径随训练走）。
不碰生产 signal_history；只观察。幂等：同日重跑先删后插。
"""
import sys, json, sqlite3, time
import numpy as np, pandas as pd
import lightgbm as lgb
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE / 'scripts')); sys.path.insert(0, str(BASE))
import min_feat_lib
import micro_feat_lib
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data
from core.db import get_tushare_db

FEAT_WIN = 60
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
TDX_FEATS = ['open30_ret','tail30_ret','vwap_dev','rv_1m','amp_intra',
             'vol_dist_am','vol_dist_tail','tail5_ret','last_vol_share']
# （B 退役 09-21：原 FEAT_NAMES+COLS 仅 B 模型用，一并摘除）

if __name__ == '__main__':
    t0 = time.time()
    # v4_big 影子（2019起样本全量重训，31维日频特征，口径=build_10d_v4_samples/train_10d_v4_pc）
    v4stats = json.loads((BASE / 'models/shadow_v4big/stats_v4big.json').read_text())
    model4 = lgb.Booster(model_file=str(BASE / 'models/shadow_v4big/model_v4big_final.txt'))

    # v4d 影子（31维 + f39/f32zha/f34/f43/f44 五个创新维度；新维度不标准化，训练原样口径）
    v4dstats = json.loads((BASE / 'models/shadow_v4d/stats_v4d.json').read_text())
    model4d = lgb.Booster(model_file=str(BASE / 'models/shadow_v4d/lgb_reg_v4d.txt'))
    V4D_NEW = ['f39_vol_diverge','f32_zha20','f34_overnight_share','f43_turn_cv20','f44_skew20']

    # v4e 影子（v4d 36维 + f50-f53 分钟微观四维；2026-09-06 上线。31维标准化用 v4e3 训练自带 stats，
    # 与 v4big/v4d 的 stats 不同——训练段不同，口径必须随训练走）
    v4estats = json.loads((BASE / 'models/shadow_v4e/stats_v4e3.json').read_text())
    model4e = lgb.Booster(model_file=str(BASE / 'models/shadow_v4e/lgb_reg_v4e3.txt'))
    V4E_MIN = ['f50_intraday_dd','f51_vol_burst','f52_downside_var','f53_kyle_illiq']

    # clf10 影子（binary 目标"跑赢10日截面中位数"，2026-09-15 上线；31维日频，
    # 标准化 stats=v10_v4 训练段口径（与 v4big 不同，训练段2022-2026），输出为概率）
    clfstats = json.loads((BASE / 'models/shadow_clf10/stats_clf10.json').read_text())
    modelf10 = lgb.Booster(model_file=str(BASE / 'models/shadow_clf10/lgb_clf_10d.txt'))

    # v4f 影子（v4d 36维 + kyle/amihud 日频微观两维；2026-09-20 上线。31维标准化用 v4f 训练
    # 自带 stats（与 v4e3 数值同源但口径随训练走），new5/micro 原值 NaN 直喂——训练即此口径）
    vfstats = json.loads((BASE / 'models/shadow_v4f/stats_v4f.json').read_text())
    modelf = lgb.Booster(model_file=str(BASE / 'models/shadow_v4f/lgb_reg_v4f.txt'))

    tcon = sqlite3.connect(BASE / 'signals.db')
    tcon.execute("""CREATE TABLE IF NOT EXISTS shadow_v4big_scores (
        date TEXT, code TEXT, score REAL,
        PRIMARY KEY (date, code))""")
    tcon.execute("""CREATE TABLE IF NOT EXISTS shadow_v4d_scores (
        date TEXT, code TEXT, score REAL,
        PRIMARY KEY (date, code))""")
    tcon.execute("""CREATE TABLE IF NOT EXISTS shadow_v4e_scores (
        date TEXT, code TEXT, score REAL,
        PRIMARY KEY (date, code))""")
    tcon.execute("""CREATE TABLE IF NOT EXISTS shadow_clf10_scores (
        date TEXT, code TEXT, score REAL,
        PRIMARY KEY (date, code))""")
    tcon.execute("""CREATE TABLE IF NOT EXISTS shadow_v4f_scores (
        date TEXT, code TEXT, score REAL,
        PRIMARY KEY (date, code))""")

    # 目标日 = 命令行参数(YYYYMMDD)或 tdx_intraday_feat 最新日期（16:10 tdx同步后 T 日特征已齐）
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        tdx_dates = [str(r[0]) for r in tcon.execute(
            "SELECT DISTINCT date FROM tdx_intraday_feat ORDER BY date").fetchall()]
        target = tdx_dates[-1]
    tdx_row = pd.read_sql_query(
        f"SELECT code, {','.join(TDX_FEATS)} FROM tdx_intraday_feat WHERE date={target}", tcon)
    tdx_map = tdx_row.set_index('code')
    print(f"目标日 {target}（tdx最新），tdx覆盖 {len(tdx_map)} 股", flush=True)

    conn = get_tushare_db()
    idx_data = load_index_data()

    # v4d 新维度依赖表：只取目标日前130个交易日窗口（f32zha需up_limit，f43需turnover_rate）
    lim_map = {}
    for tc, dt_, ul in conn.execute(
            f"SELECT ts_code, trade_date, up_limit FROM stk_limit WHERE trade_date > ("
            f"SELECT MIN(trade_date) FROM (SELECT DISTINCT trade_date FROM daily "
            f"WHERE trade_date <= '{target}' ORDER BY trade_date DESC LIMIT 130))").fetchall():
        lim_map.setdefault(str(tc), {})[str(dt_)] = float(ul) if ul is not None else None
    turn_map = {}
    for tc, dt_, tr_ in conn.execute(
            f"SELECT ts_code, trade_date, turnover_rate FROM daily_basic WHERE trade_date > ("
            f"SELECT MIN(trade_date) FROM (SELECT DISTINCT trade_date FROM daily "
            f"WHERE trade_date <= '{target}' ORDER BY trade_date DESC LIMIT 130))").fetchall():
        turn_map.setdefault(str(tc), {})[str(dt_)] = float(tr_) if tr_ is not None else None
    # daily.trade_date 口径: YYYYMMDD（无横线），全脚本统一 YYYYMMDD 比较
    stocks = [r[0] for r in conn.execute(
        "SELECT symbol, name FROM stock_basic WHERE market != '北交所'").fetchall()
        if not any(s in (r[1] or '') for s in ('ST','st','退'))
        and not r[0].startswith(('8','4','92'))]

    # 起点：目标日前约130个交易日（60天窗+余量；v4d 的 f39 需 61+60=121 日窗）
    cut = conn.execute(
        f"SELECT MIN(trade_date) FROM (SELECT DISTINCT trade_date FROM daily "
        f"WHERE trade_date <= '{target}' "
        f"ORDER BY trade_date DESC LIMIT 130)").fetchone()[0]

    rows, codes, new5 = [], [], []
    skipped = 0
    for code in stocks:
        if code not in tdx_map.index:
            skipped += 1; continue
        ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
        dfr = conn.execute(
            "SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol, open, pre_close FROM daily "
            f"WHERE ts_code='{ts_code}' AND trade_date >= '{cut}' AND trade_date <= '{target}' ORDER BY trade_date").fetchall()
        if not dfr or str(dfr[-1][0])[:10] != target:
            skipped += 1; continue          # T日无日线（停牌）
        if len(dfr) < FEAT_WIN + 1:
            skipped += 1; continue
        closes = [float(r[1]) for r in dfr]; highs = [float(r[2]) for r in dfr]
        lows = [float(r[3]) for r in dfr]
        pcts = [float(r[4])/100.0 for r in dfr]; vols = [float(r[5]) for r in dfr]
        dates = [str(r[0])[:10] for r in dfr]
        adj_rows = conn.execute(
            "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",
            [ts_code]).fetchall()
        ac, ah, al = apply_forward_adjust(closes, highs, lows, adj_rows)
        idx_info = idx_data.get(get_board_index(code))
        idx_dict = None
        if idx_info and dates[-1] in idx_info.get('dict', {}):
            idx_dict = {d: v for d, v in idx_info['dict'].items() if d <= dates[-1]}
        f38 = compute_features(ac[-FEAT_WIN-1:], ah[-FEAT_WIN-1:], al[-FEAT_WIN-1:],
                               vols[-FEAT_WIN-1:], pcts[-FEAT_WIN-1:], idx_dict,
                               {'ep':0.5,'bp':0.5,'ln_cap':22.0})
        # 与训练时对齐：训练 win 是 [i-60, i] 共61个点，取 f38 的第 FEAT_WIN 个窗终点值
        base = f38 if isinstance(f38, list) else list(f38)
        tr = tdx_map.loc[code]
        feat = [base[j] for j in PV_INDICES] + [float(tr[k]) for k in TDX_FEATS]

        # ---- v4d 五个创新维度（口径逐字对齐 _build_v4c_0905.py，未复权原值，NaN 保留给 LGBM）----
        dr = [str(r[0]) for r in dfr]
        o_arr = np.array([float(r[6]) for r in dfr]); pc_arr = np.array([float(r[7]) for r in dfr])
        uls = np.array([lim_map.get(ts_code, {}).get(dt8) for dt8 in dr], dtype=float)
        tofs = np.array([turn_map.get(ts_code, {}).get(dt8) for dt8 in dr], dtype=float)
        def _roll(a, w, mp, fn):
            s = pd.Series(a, dtype=float)
            if len(s) < mp: return np.nan
            v = fn(s.rolling(w, min_periods=mp))
            return float(v.iloc[-1]) if pd.notna(v.iloc[-1]) else np.nan
        # f39 量能背离（61日新高 → 1 - 当日量/前60日峰值量）
        hh = _roll(highs, 61, 40, lambda r: r.max())
        if np.isfinite(hh) and highs[-1] >= hh:
            pk = _roll(vols[:-1], 60, 40, lambda r: r.max())
            f39 = float(1 - vols[-1] / pk) if np.isfinite(pk) and pk > 0 else np.nan
        else:
            f39 = np.nan
        # f32 炸板率20（触板未封/触板，min_periods=5）
        touch = ((highs >= uls * 0.998) & np.isfinite(uls)).astype(float)
        seal = ((closes >= uls * 0.998) & np.isfinite(uls)).astype(float)
        tb = np.where((touch > 0) & (seal == 0), 1.0, 0.0)
        # touch/tb 全序列 rolling(20,min5).sum() 末值（同 build 口径）
        ts_ = pd.Series(touch).rolling(20, min_periods=5).sum().iloc[-1]
        bs_ = pd.Series(tb).rolling(20, min_periods=5).sum().iloc[-1]
        f32z = float(bs_ / ts_) if pd.notna(ts_) and ts_ > 0 and pd.notna(bs_) else np.nan
        # f34 隔夜动量占比20
        on = np.where(pc_arr > 0, o_arr / pc_arr - 1, np.nan)
        io = np.where(o_arr > 0, closes / o_arr - 1, np.nan)
        on_s = pd.Series(on).rolling(20, min_periods=15).sum().iloc[-1]
        io_s = pd.Series(np.abs(io)).rolling(20, min_periods=15).sum().iloc[-1]
        f34 = float(on_s / (io_s + 1e-9)) if pd.notna(on_s) and pd.notna(io_s) else np.nan
        # f43 换手率变异系数20
        tv_m = pd.Series(tofs).rolling(20, min_periods=15).mean().iloc[-1]
        tv_s = pd.Series(tofs).rolling(20, min_periods=15).std().iloc[-1]
        f43 = float(tv_s / tv_m) if pd.notna(tv_m) and tv_m > 0 and pd.notna(tv_s) else np.nan
        # f44 收益偏度20（ret=pct/100 同 build）
        sk = pd.Series(np.array(pcts, dtype=float)).rolling(20, min_periods=15).skew().iloc[-1]
        f44 = float(sk) if pd.notna(sk) else np.nan

        rows.append(feat); new5.append([f39, f32z, f34, f43, f44]); codes.append(code)

    Xbase = np.array([r[:31] for r in rows], dtype=np.float64)
    if Xbase.size == 0 or Xbase.shape[0] < 100:
        print(f"⚠️ 目标日 {target} 可打分股票仅 {len(rows)}（tdx覆盖{len(tdx_map)}），不足100，跳过不写")
        sys.exit(0)

    # v4_big 影子打分：31维日频特征，clip+zscore 用 v10_v4_stats_big 口径（feat_0..feat_30 列序）
    X4 = Xbase.copy()
    for j in range(31):
        st = v4stats[f'feat_{j}']
        sd = st['std'] if st['std'] > 0 else 1.0
        X4[:, j] = (np.clip(X4[:, j], st['low'], st['high']) - st['mean']) / sd
    X4 = np.nan_to_num(X4, nan=0.0)
    pred4 = model4.predict(X4)

    # clf10 影子打分：31维原始特征按 clf10 训练自带 stats 标准化（训练段2022-2026，与 v4big 不同）
    Xf10 = Xbase.copy()
    for j in range(31):
        st = clfstats[f'feat_{j}']
        sd = st['std'] if st['std'] > 0 else 1.0
        Xf10[:, j] = (np.clip(Xf10[:, j], st['low'], st['high']) - st['mean']) / sd
    Xf10 = np.nan_to_num(Xf10, nan=0.0)
    predf10 = modelf10.predict(Xf10)

    # v4d 影子打分：标准化后的31维 + 5个原始新维度（NaN 原生交给 LGBM，训练口径如此）
    X4d = np.hstack([X4, np.array(new5, dtype=np.float64)])
    pred4d = model4d.predict(X4d)

    # v4e 影子打分：31维按 v4e3 训练自带 stats 标准化（训练段2025-04起，clip/zscore 与 v4big 不同，
    # 口径必须随训练走）+ new5 + f50-f53（分钟微观，不标准化）。
    # 分钟库缺票/缺日 → NaN 交给 LGBM（训练口径）。
    X4e = Xbase.copy()
    for j in range(31):
        st = v4estats[f'f{j}']
        sd = st['std'] if st['std'] > 0 else 1.0
        X4e[:, j] = (np.clip(X4e[:, j], st['low'], st['high']) - st['mean']) / sd
    mf = min_feat_lib.min_feats_for_date(target)
    if len(mf):
        m4 = {k: dict(zip(mf['code'], mf[k])) for k in V4E_MIN}
        # 09-06 修复：拼 X4e（v4e3 自带 stats 标准化），不是 X4（v4big stats）——训练口径随训练走
        X4e = np.hstack([X4e, np.array(new5, dtype=np.float64),
                         np.array([[m4[k].get(c, np.nan) for k in V4E_MIN] for c in codes], dtype=float)])
        pred4e = model4e.predict(X4e)
        print(f"v4e 分钟特征覆盖 {len(mf)}/{len(codes)}", flush=True)
    else:
        pred4e = None
        print("⚠️ v4e 跳过：分钟库无目标日数据（min5_incr 未跑或失败）", flush=True)

    # v4f 影子打分：31维按 v4f 训练自带 stats 标准化 + new5 原值 + kyle/amihud 原值
    # （micro_feat_lib 口径=发现轮 _microstructure_ic_0919；分钟库缺票/缺日 → NaN 直喂，训练口径）
    X4f = Xbase.copy()
    for j in range(31):
        st = vfstats[f'f{j}']
        sd = st['std'] if st['std'] > 0 else 1.0
        X4f[:, j] = (np.clip(X4f[:, j], st['low'], st['high']) - st['mean']) / sd
    mft = micro_feat_lib.micro_feats_for_date(target)
    if len(mft):
        m2 = {k: dict(zip(mft['code'], mft[k])) for k in micro_feat_lib.MICRO2}
        X4f = np.hstack([X4f, np.array(new5, dtype=np.float64),
                         np.array([[m2[k].get(c, np.nan) for k in micro_feat_lib.MICRO2] for c in codes], dtype=float)])
        predf = modelf.predict(X4f)
        print(f"v4f 微观特征覆盖 {len(mft)}/{len(codes)}", flush=True)
    else:
        predf = None
        print("⚠️ v4f 跳过：分钟库无目标日数据（min5_incr 未跑或失败）", flush=True)

    tcon.execute("DELETE FROM shadow_v4big_scores WHERE date=?", (target,))
    tcon.executemany("INSERT INTO shadow_v4big_scores VALUES (?,?,?)",
                     [(target, c, float(p)) for c, p in zip(codes, pred4)])
    tcon.execute("DELETE FROM shadow_v4d_scores WHERE date=?", (target,))
    tcon.executemany("INSERT INTO shadow_v4d_scores VALUES (?,?,?)",
                     [(target, c, float(p)) for c, p in zip(codes, pred4d)])
    if pred4e is not None:
        tcon.execute("DELETE FROM shadow_v4e_scores WHERE date=?", (target,))
        tcon.executemany("INSERT INTO shadow_v4e_scores VALUES (?,?,?)",
                         [(target, c, float(p)) for c, p in zip(codes, pred4e)])
    tcon.execute("DELETE FROM shadow_clf10_scores WHERE date=?", (target,))
    tcon.executemany("INSERT INTO shadow_clf10_scores VALUES (?,?,?)",
                     [(target, c, float(p)) for c, p in zip(codes, predf10)])
    if predf is not None:
        tcon.execute("DELETE FROM shadow_v4f_scores WHERE date=?", (target,))
        tcon.executemany("INSERT INTO shadow_v4f_scores VALUES (?,?,?)",
                         [(target, c, float(p)) for c, p in zip(codes, predf)])
    tcon.commit()
    print(f"影子打分 {len(codes)} 股（跳过{skipped}）写入 shadow_v4big_scores + shadow_v4d_scores"
          + (" + shadow_v4e_scores" if pred4e is not None else "（v4e跳过）")
          + (" + shadow_v4f_scores" if predf is not None else "（v4f跳过）")
          + f" date={target} "
          f"v4big范围 {pred4.min():.3f}~{pred4.max():.3f} "
          f"v4d范围 {pred4d.min():.3f}~{pred4d.max():.3f}"
          + (f" v4e范围 {pred4e.min():.3f}~{pred4e.max():.3f}" if pred4e is not None else "")
          + (f" v4f范围 {predf.min():.3f}~{predf.max():.3f}" if predf is not None else "")
          + f" 耗时{time.time()-t0:.0f}s")