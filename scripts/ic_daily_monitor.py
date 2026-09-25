#!/usr/bin/env python3
"""每日模型IC监控 — 验证v4模型实盘有效性

改进：当天只保存预测值，等未来20日数据出现后回溯计算真实IC。
运行时间: 每日15:30后（日线更新完毕）
保存预测到 _model_ic_predictions.parquet
记录IC到 _model_ic_log.csv（仅当有真实数据时写入）
性能：GTJA pickle和指数数据仅加载一次，不使用循环内逐行查询
特征维度：49维（38基础+11GTJA），与训练脚本retrain_20d.py完全一致
"""
import os, json, time, duckdb, numpy as np, pandas as pd, lightgbm as lgb, gzip, pickle
from scipy import stats
from pathlib import Path
from datetime import datetime, timedelta

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
MODEL_DIR = BASE / 'models'
LOG_PATH = BASE / '_model_ic_log.csv'
PRED_PATH = BASE / '_model_ic_predictions.parquet'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'

# 训练脚本取前11个GTJA因子（按字母/数字排序）
GTJA_ALL = ['gtja_001','gtja_002','gtja_003','gtja_004','gtja_005',
            'gtja_006','gtja_007','gtja_008','gtja_009','gtja_010','gtja_011',
            'gtja_083','gtja_177','gtja_184']
GTJA_NAMES = GTJA_ALL[:11]  # 前11个

def _load_norm_stats():
    stats_path = BASE / 'models' / 'v6_norm_stats.json'
    if stats_path.exists():
        with open(stats_path) as f:
            return json.load(f)
    return None

NORM_STATS = _load_norm_stats()

# 一次性加载GTJA
GTJA_RESULTS = {}
try:
    if GTJA_PKL.exists():
        with gzip.open(str(GTJA_PKL), 'rb') as f:
            GTJA_RESULTS = pickle.load(f)
except Exception:
    pass


def compute_features_batch(con, latest_str):
    """批量计算所有股票的特征向量 — 49维(38基础+11GTJA)，与retrain_20d.py一致
    
    特征顺序（38基础）:
    0-4: chg5,chg10,chg20,chg60,chg120(=chg60)
    5-9: d5,d10,d20,d60,d120(=d60)
    10-11: bull1,bull2
    12-17: rr,std20,vr,pos,nh,vpc
    18-19: c1d,c3d
    20-22: ep,bp,ln_cap
    23-25: ex5,ex10,ex20
    26-37: skew20,kurt20,dn_streak,up_ratio10,vol_chg,rel_str,kurt60,slope5,slope10,accel,vp_shrink,vp_div
    """
    t0 = time.time()

    # 1. 取最新日所有股票的120天日线（批量一次性）
    daily_raw = con.execute(f"""
        SELECT stock_code, date, close, COALESCE(change_pct,0) as chg, COALESCE(amount,0) as amt
        FROM stock_daily
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY date DESC) <= 120
    """).fetchdf()

    print(f"  📥 加载日线数据: {len(daily_raw)}行, {daily_raw['stock_code'].nunique()}只, {time.time()-t0:.1f}s")

    # 2. 取估值数据
    val_raw = con.execute(f"""
        SELECT DISTINCT ON (stock_code) stock_code, pe_ttm, pb, total_mv
        FROM stock_valuation
        ORDER BY stock_code, date DESC
    """).fetchdf()

    if len(val_raw) > 0:
        val_dict = {}
        for _, r in val_raw.iterrows():
            val_dict[r['stock_code']] = (r['pe_ttm'], r['pb'], r['total_mv'])
    else:
        val_dict = {}

    # 3. 取上证指数最新120天close（从 index_daily 取，stock_daily 的 000001 是平安银行！）
    idx_raw = con.execute(f"""
        SELECT date, close FROM index_daily WHERE index_code='000001'
        ORDER BY date DESC LIMIT 120
    """).fetchdf()
    if len(idx_raw) >= 120:
        idx_raw = idx_raw.sort_values('date')
        idx_closes = idx_raw['close'].values.astype(np.float64)
        idx_latest = idx_closes[-1]
    else:
        idx_closes = np.array([])
        idx_latest = np.nan

    # 4. 按股票分组处理
    groups = daily_raw.groupby('stock_code')
    results = []
    t1 = time.time()

    for g_idx, (code, grp) in enumerate(groups):
        grp = grp.sort_values('date')
        c_arr = grp['close'].values.astype(np.float64)
        r_arr = grp['chg'].values.astype(np.float64) / 100.0
        a_arr = grp['amt'].values.astype(np.float64)

        n = len(c_arr)
        if n < 60:  # 至少60天数据
            continue

        lc = c_arr[-1]

        # ========== 0-4: 收益类 ==========
        chg5 = lc / c_arr[-5] - 1 if c_arr[-5] > 0 else 0
        chg10 = lc / c_arr[-10] - 1 if c_arr[-10] > 0 else 0
        chg20 = lc / c_arr[-20] - 1 if c_arr[-20] > 0 else 0
        chg60 = lc / c_arr[-60] - 1 if c_arr[-60] > 0 else 0
        chg120 = chg60  # 与训练脚本一致

        # ========== 5-9: 均线偏离 ==========
        ma5 = np.mean(c_arr[-5:])
        ma10 = np.mean(c_arr[-10:])
        ma20 = np.mean(c_arr[-20:])
        ma60 = np.mean(c_arr[-60:])
        d5 = lc / ma5 - 1 if ma5 > 0 else 0
        d10 = lc / ma10 - 1 if ma10 > 0 else 0
        d20 = lc / ma20 - 1 if ma20 > 0 else 0
        d60 = lc / ma60 - 1 if ma60 > 0 else 0
        d120 = d60  # 与训练脚本一致

        # ========== 10-11: 均线多头/多头2 ==========
        bull1 = 1 if ma5 > ma10 > ma20 else 0
        bull2 = 1 if ma20 > ma60 else 0

        # ========== 12-17: 波动率/量比/位置/信号 ==========
        w20 = c_arr[-20:]
        rl = np.min(w20)
        rh = np.max(w20)
        rr = (rh - rl) / rl * 100 if rl > 0 else 0
        std20 = np.std(w20) / np.mean(w20) * 100 if np.mean(w20) > 0 else 0

        vols = a_arr[-20:]
        vr = vols[-1] / np.mean(vols) if np.mean(vols) > 0 else 1

        # 位置
        pos = (lc - rl) / (rh - rl) * 100 if rh != rl else 50
        nh = 1 if lc > rh * 0.97 else 0
        vpc = 1 if chg5 > 0.01 and vr > 1.2 else 0

        # ========== 18-19: c1d, c3d ==========
        c1d = r_arr[-1] if len(r_arr) > 0 else 0
        c3d = lc / c_arr[-3] - 1 if len(c_arr) >= 3 and c_arr[-3] > 0 else 0

        # ========== 20-22: 估值 ==========
        val = val_dict.get(code)
        ep, bp, ln_cap = 0.5, 0.5, 22.0
        if val:
            if val[0] and val[0] > 0:
                ep = 1.0 / val[0]
            if val[1] and val[1] > 0:
                bp = 1.0 / val[1]
            if val[2] and val[2] > 0:
                ln_cap = np.log(val[2])

        # ========== 23-25: 超额收益 ==========
        if len(idx_closes) >= 120 and n >= 20:
            ex5 = lc / c_arr[-5] - idx_latest / idx_closes[-5] if c_arr[-5] > 0 and idx_closes[-5] > 0 else 0
            ex10 = lc / c_arr[-10] - idx_latest / idx_closes[-10] if c_arr[-10] > 0 and idx_closes[-10] > 0 else 0
            ex20 = lc / c_arr[-20] - idx_latest / idx_closes[-20] if c_arr[-20] > 0 and idx_closes[-20] > 0 else 0
        else:
            ex5 = ex10 = ex20 = 0

        # ========== 26-37: 高阶统计特征 ==========
        p = np.diff(c_arr) / c_arr[:-1]  # 收益率序列

        # 26: skew20
        skew20 = float(stats.skew(w20)) if len(w20) >= 20 else 0

        # 27: kurt20 (正态kurtosis=3)
        kurt20 = float(stats.kurtosis(w20, fisher=False)) if len(w20) >= 20 else 3

        # 28: dn_streak (连续下跌天数)
        dn_streak = 0
        for s in reversed(np.sign(p[-20:])):
            if s < 0:
                dn_streak += 1
            else:
                break

        # 29: up_ratio10
        up_ratio10 = np.sum(np.sign(p[-10:]) > 0) / 10. if len(p) >= 10 else 0.5

        # 30: vol_chg (波动率变化率)
        if n >= 60:
            vo = float(np.std(p[-59:-19]) * np.sqrt(252))
            vn = float(np.std(p[-19:]) * np.sqrt(252))
            vol_chg = vn / vo - 1 if vo > 0 else 0
        else:
            vol_chg = 0

        # 31: rel_str (相对强度)
        ma20_local = np.mean(w20)
        ma60_local = np.mean(c_arr[-60:]) if n >= 60 else ma20_local
        rel_str = chg5 - (ma20_local / ma60_local - 1) if ma60_local > 0 else 0

        # 32: kurt60
        w60 = c_arr[-60:]
        kurt60 = float(stats.kurtosis(w60, fisher=False)) if len(w60) >= 60 else 3

        # 33-35: slope5, slope10, accel
        if len(w20) >= 10:
            x5 = np.arange(5)
            y5 = w20[-5:]
            s5 = float(np.sum((x5 - x5.mean()) * (y5 - y5.mean())) / np.sum((x5 - x5.mean()) ** 2)) if np.sum((x5 - x5.mean()) ** 2) > 0 else 0
            x10 = np.arange(10)
            y10 = w20[-10:]
            s10 = float(np.sum((x10 - x10.mean()) * (y10 - y10.mean())) / np.sum((x10 - x10.mean()) ** 2)) if np.sum((x10 - x10.mean()) ** 2) > 0 else 0
            slope5 = s5
            slope10 = s10
            accel = s5 - s10
        else:
            slope5 = slope10 = accel = 0

        # 36: vp_shrink (缩量下跌)
        vr20 = vols[-1] / np.mean(vols) if np.mean(vols) > 0 else 1
        vp_shrink = 1 if chg5 < -0.01 and vr20 < 0.7 else 0

        # 37: vp_div (量价背离)
        vp_div = 1 if (chg5 > 0 and vr20 < 0.8) or (chg5 < 0 and vr20 > 1.2) else 0

        # 组装38维基础特征
        base = np.array([
            chg5, chg10, chg20, chg60, chg120,  # 0-4
            d5, d10, d20, d60, d120,  # 5-9
            bull1, bull2,  # 10-11
            rr, std20, vr, pos, nh, vpc,  # 12-17
            c1d, c3d,  # 18-19
            ep, bp, ln_cap,  # 20-22
            ex5, ex10, ex20,  # 23-25
            skew20, kurt20, dn_streak, up_ratio10, vol_chg, rel_str,  # 26-31
            kurt60, slope5, slope10, accel, vp_shrink, vp_div  # 32-37
        ], dtype=np.float64)

        # ========== GTJA因子 ==========
        gt = []
        for gn in GTJA_NAMES:
            sig = GTJA_RESULTS.get(gn)
            if sig is not None and latest_str in sig.index and code in sig.columns:
                v = sig.loc[latest_str, code]
                gt.append(float(v) if not np.isnan(v) else 0.0)
            else:
                # 向前查找最近的有效值
                found = False
                for offset in range(1, 16):
                    prev_date = (datetime.strptime(latest_str, '%Y-%m-%d') - timedelta(days=offset)).strftime('%Y-%m-%d')
                    if prev_date in sig.index and code in sig.columns:
                        v = sig.loc[prev_date, code]
                        gt.append(float(v) if not np.isnan(v) else 0.0)
                        found = True
                        break
                if not found:
                    gt.append(0.0)

        gtja_v = np.array(gt, dtype=np.float64)

        # 49维 = 38基础 + 11GTJA（回归模型用）
        feat = np.append(base, gtja_v)

        # 42维 = 38基础 + 4GTJA（cls27分类模型用）
        gtja_v_cls = gtja_v[:4]  # 前4个GTJA因子
        cls27_feat = np.append(base, gtja_v_cls)

        results.append((code, feat, cls27_feat))

    print(f"  ⏱ 特征计算: {len(results)}只, {time.time()-t1:.1f}s")
    return results


def compute_ic(preds, fwd_rets):
    """计算Spearman IC"""
    fr = np.asarray(fwd_rets, dtype=np.float64)
    pr = np.asarray(preds, dtype=np.float64)
    valid = np.isfinite(fr) & np.isfinite(pr)
    if valid.sum() >= 30:
        ic = stats.spearmanr(pr[valid], fr[valid])[0]
        return ic, int(valid.sum())
    return 0.0, int(valid.sum())


def backfill_ic():
    """回溯计算历史预测日期的真实IC，更新CSV日志"""
    if not PRED_PATH.exists():
        return

    con = duckdb.connect(str(DB), read_only=True)

    try:
        pred_df = pd.read_parquet(PRED_PATH)

        # 找fwd_ret为空的日期
        needs_backfill = pred_df[pred_df['fwd_ret'].isna()]
        if len(needs_backfill) == 0:
            return

        # 取所有为空记录的日期
        na_dates = sorted(needs_backfill['date'].unique())

        # 分批查未来数据
        updated_count = 0
        for dt in na_dates:
            # 这批日期的代码
            sub = pred_df[(pred_df['date'] == dt) & (pred_df['fwd_ret'].isna())]
            codes = sub['stock_code'].tolist()

            # 批量查未来收益
            codes_str = ','.join([f"'{c}'" for c in codes])
            future_rows = con.execute(f"""
                SELECT stock_code, date, close FROM stock_daily
                WHERE stock_code IN ({codes_str}) AND date >= '{dt}'
                ORDER BY stock_code, date
            """).fetchdf()

            if len(future_rows) == 0:
                continue

            fwd_map = {}
            for code, grp in future_rows.groupby('stock_code'):
                grp = grp.sort_values('date')
                c = grp['close'].values.astype(np.float64)
                # 需要至少21个数据点(预测日+20个未来交易日)
                if len(c) >= 21 and c[0] > 0:
                    # fwd_ret = 20日后的收盘 / 预测日收盘 - 1
                    fwd_map[code] = float(c[20] / c[0] - 1)

            if not fwd_map:
                continue

            for idx in sub.index:
                code = pred_df.at[idx, 'stock_code']
                if code in fwd_map:
                    pred_df.at[idx, 'fwd_ret'] = fwd_map[code]
                    updated_count += 1

        if updated_count > 0:
            pred_df.to_parquet(str(PRED_PATH))

            # 按日期分组计算IC
            ic_records = []
            for dt in sorted(pred_df['date'].unique()):
                sub = pred_df[pred_df['date'] == dt]
                sub_valid = sub.dropna(subset=['fwd_ret'])
                if len(sub_valid) >= 30:
                    reg_ic, valid_n = compute_ic(
                        sub_valid['pred_reg'].values,
                        sub_valid['fwd_ret'].values
                    )
                    cls_ic, _ = compute_ic(
                        sub_valid['pred_cls'].values,
                        sub_valid['fwd_ret'].values
                    )
                    ic_records.append({
                        'date': dt,
                        'reg_ic': 0.0 if np.isnan(reg_ic) else round(float(reg_ic), 4),
                        'cls_ic': 0.0 if np.isnan(cls_ic) else round(float(cls_ic), 4),
                        'samples': len(sub),
                        'valid': valid_n
                    })

            if ic_records:
                ic_df = pd.DataFrame(ic_records)
                ic_df.to_csv(LOG_PATH, index=False)
                print(f"  🔄 回溯更新 {len(ic_records)} 天IC, {updated_count}条未来收益")

                # 显示最近一次有效IC
                today = datetime.now().strftime('%Y-%m-%d')
                past = ic_df[ic_df['date'] < today].sort_values('date', ascending=False)
                if len(past) > 0:
                    last = past.iloc[0]
                    print(f"  📊 最新回溯IC ({last['date']}): reg={last['reg_ic']:+.4f}, cls={last['cls_ic']:+.4f}, 有效{int(last['valid'])}样本")

    finally:
        con.close()


def main():
    t0 = time.time()
    today = datetime.now().strftime('%Y-%m-%d')

    print(f"IC监控 — {today}")
    print("="*50)

    # 加载模型
    reg_path = MODEL_DIR / 'lgb_reg_model.txt'
    if not reg_path.exists():
        print("❌ 回归模型文件不存在")
        return
    reg = lgb.Booster(model_file=str(reg_path))
    print(f"✅ 模型加载: reg={reg.num_trees()}trees (20d)")

    cls_path = MODEL_DIR / 'lgb_cls_model.txt'
    clf = None
    if cls_path.exists():
        clf = lgb.Booster(model_file=str(cls_path))
        print(f"✅ cls27加载: {clf.num_trees()}trees")

    if GTJA_PKL.exists():
        print(f"✅ GTJA加载: {len(GTJA_NAMES)}个因子 (一次性，{len(GTJA_RESULTS.get('gtja_006',[]))}条)")

    # 第一步：回溯历史IC
    print("\n=== 回溯计算历史IC ===")
    backfill_ic()

    # 第二步：处理今天的预测
    print("\n=== 今日预测 ===")
    con = duckdb.connect(str(DB), read_only=True)

    latest_date = con.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    latest_str = str(latest_date)[:10]
    print(f"最新交易日: {latest_str}")

    results = compute_features_batch(con, latest_str)
    if len(results) == 0:
        print("❌ 无有效股票数据")
        con.close()
        return

    # 批量预测
    X = np.nan_to_num(np.array([r[1] for r in results]), nan=0.0)
    X_cls = np.nan_to_num(np.array([r[2] for r in results]), nan=0.0)

    print(f"  特征维度: X={X.shape}, X_cls={X_cls.shape}")
    pred_reg = reg.predict(X)
    pred_cls = clf.predict(X_cls) if clf is not None else np.zeros(len(results))

    codes = [r[0] for r in results]
    t1 = time.time()

    # 构建新的预测记录
    new_records = []
    for i, code in enumerate(codes):
        new_records.append({
            'date': latest_str,
            'stock_code': code,
            'pred_reg': round(float(pred_reg[i]), 6),
            'pred_cls': round(float(pred_cls[i]), 6),
            'fwd_ret': None
        })

    new_df = pd.DataFrame(new_records)
    print(f"  预测完成: {len(new_df)}只股票, {time.time()-t1:.1f}s")

    # 追加到parquet
    if PRED_PATH.exists():
        old_df = pd.read_parquet(PRED_PATH)
        # 去重：同一天只保留最新
        old_df = old_df[~(old_df['date'].astype(str) == latest_str)]
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_parquet(str(PRED_PATH))
    print(f"  💾 预测已保存: {len(new_df)}条, 总{len(combined)}条记录")

    # 今日结果
    print(f"\n  ⏳ {latest_str} 刚收盘，未来20日收益未产生，预测值已保存待回溯计算真实IC")

    # 累计统计
    if LOG_PATH.exists():
        log_df = pd.read_csv(LOG_PATH)
        if len(log_df) >= 2:
            avg_reg = log_df['reg_ic'].mean()
            avg_cls = log_df['cls_ic'].mean()
            pos_rate = (log_df['reg_ic'] > 0.05).mean() * 100
            print(f"\n📈 累计IC({len(log_df)}天有效数据):")
            print(f"  平均reg IC: {avg_reg:+.4f}  平均cls27 IC: {avg_cls:+.4f}")
            print(f"  reg IC>0.05天数占比: {pos_rate:.0f}%")
    else:
        print(f"\n  (尚无IC记录，等待未来20日数据积累)")

    con.close()
    print(f"\n⏱ 总耗时: {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
