#!/usr/bin/env python3
"""20d 重训实验（2026-09-06，v4d 对齐）：samples_v20_base(31维) + v4d 5个新特征
训练两版：31 基线 / 36 特征 → 逐日 RankIC 配对检验（验证 5 特征对 20d 是否有增量）
方法学（照抄 v4d）：按日期 80% 切分、31 维标准化只用训练段、5 新特征原生 NaN
⚠️ 本版修正 v4d 的坑：norm_stats 必须存文件（stats 键 f0..f30 + 特征名）
"""
import json, time
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy import stats
from pathlib import Path

BASE = Path.home() / ".hermes/stockdb" / "analysis" / "retrain_20d_v36"
t0 = time.time()

def load_df():
    sm = pd.read_parquet(BASE / "samples_v20_base.parquet")
    uf_path = BASE.parent / "retrain_10d_v4" / "_uncon_feats.parquet"  # 候选特征库在 10d v4 目录
    uf = pd.read_parquet(uf_path).rename(columns={"symbol": "code"})
    uf = uf.drop(columns=[c for c in ["f31_touch20", "f32_wick20", "f33_pvcorr20"] if c in uf.columns])
    return sm.merge(uf, on=["code", "date"], how="left")

def train(extra_feats, out_prefix):
    df = load_df()
    feats31 = [f"f{j}" for j in range(31)]
    feats = feats31 + extra_feats
    print(f"[{out_prefix}] 样本 {len(df):,}  日期 {df.date.min()} ~ {df.date.max()}  "
          f"缺失率 { {c: round(float(df[c].isna().mean()), 3) for c in extra_feats} }", flush=True)
    dates = np.sort(df["date"].unique())
    split = dates[int(len(dates) * 0.8)]
    tr = df[df["date"] < split]
    va = df[df["date"] >= split]
    print(f"[{out_prefix}] 切分日 {split}  训练 {len(tr):,} / 验证 {len(va):,}  ({va.date.nunique()} 验证日)", flush=True)
    Xtr = tr[feats].to_numpy(float).copy()
    Xva = va[feats].to_numpy(float).copy()
    ytr = tr["y"].to_numpy(float)
    yva = va["y"].to_numpy(float)
    # 31 维训练段标准化 + 存 stats（v4d 教训：必须落盘）
    stats_dict = {}
    for j in range(31):
        v = Xtr[:, j]
        v = v[np.isfinite(v)]
        lo, hi = np.percentile(v, 1), np.percentile(v, 99)
        mu, sd = float(v.mean()), float(v.std())
        stats_dict[feats[j]] = {"mean": mu, "std": sd, "low": float(lo), "high": float(hi)}
        Xtr[:, j] = (np.clip(Xtr[:, j], lo, hi) - mu) / sd
        Xva[:, j] = (np.clip(Xva[:, j], lo, hi) - mu) / sd
    if extra_feats:  # 新特征：保留 NaN 给 LGBM 原生处理
        Xtr[:, 31:] = np.where(np.isfinite(Xtr[:, 31:]), Xtr[:, 31:], np.nan)
        Xva[:, 31:] = np.where(np.isfinite(Xva[:, 31:]), Xva[:, 31:], np.nan)
    Xtr = np.nan_to_num(Xtr[:, :31], nan=0.0) if not extra_feats else np.concatenate(
        [np.nan_to_num(Xtr[:, :31], nan=0.0), Xtr[:, 31:]], axis=1)
    Xva = np.nan_to_num(Xva[:, :31], nan=0.0) if not extra_feats else np.concatenate(
        [np.nan_to_num(Xva[:, :31], nan=0.0), Xva[:, 31:]], axis=1)
    params = {"objective": "regression", "metric": "l2", "num_leaves": 15, "learning_rate": 0.008,
              "feature_fraction": 0.6, "bagging_fraction": 0.6, "bagging_freq": 5,
              "min_data_in_leaf": 300, "lambda_l1": 0.5, "lambda_l2": 2.0, "max_depth": 5,
              "min_gain_to_split": 0.2, "verbose": 0, "num_threads": 8}
    model = lgb.train(params, lgb.Dataset(Xtr, ytr), num_boost_round=2000,
                      valid_sets=[lgb.Dataset(Xtr, ytr), lgb.Dataset(Xva, yva)],
                      valid_names=["train", "val"],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(500)])
    pred = model.predict(Xva)
    # 逐日截面 RankIC
    vd = va["date"].to_numpy()
    recs = []
    for d in np.unique(vd):
        m = vd == d
        if m.sum() >= 200:
            recs.append({"date": str(d), "n": int(m.sum()),
                         "rank_ic": float(stats.spearmanr(pred[m], yva[m])[0])})
    ics = [r["rank_ic"] for r in recs]
    print(f"[{out_prefix}] 树数 {model.num_trees()}  验证日均IC {np.mean(ics):+.4f}  "
          f"正占比 {np.mean([i > 0 for i in ics]) * 100:.0f}%  ({len(ics)} 天)  耗时 {time.time()-t0:.0f}s", flush=True)
    # 十分组
    pairs = sorted(zip(pred, yva), key=lambda x: x[0])
    d10 = max(1, len(pairs) // 10)
    dec = [float(np.mean([r for _, r in pairs[k*d10:(k+1)*d10]])) * 100 for k in range(10)]
    print(f"[{out_prefix}] 十分组: " + " ".join(f"D{k+1}:{v:+.2f}%" for k, v in enumerate(dec)), flush=True)
    # 保存（模型 + stats 成对 + 逐日 IC）
    model.save_model(str(BASE / f"{out_prefix}.txt"))
    json.dump(stats_dict, open(BASE / f"{out_prefix}_stats.json", "w"), indent=1)
    pd.DataFrame(recs).to_csv(BASE / f"daily_ic_{out_prefix}.csv", index=False)
    return {"out": out_prefix, "n_samples": int(len(df)), "n_features": len(feats),
            "split_date": str(split), "n_train": int(len(tr)), "n_val": int(len(va)),
            "best_iteration": int(model.best_iteration), "num_trees": int(model.num_trees()),
            "val_daily_rank_ic_mean": float(np.mean(ics)), "val_days": len(ics),
            "pos_ic_ratio": float(np.mean([i > 0 for i in ics])), "deciles_pct": dec,
            "feats": feats}

if __name__ == "__main__":
    V4D_EXTRA = ["f39_vol_diverge", "f32_zha20", "f34_overnight_share", "f43_turn_cv20", "f44_skew20"]
    r31 = train([], "lgb_reg_20d_31")
    r36 = train(V4D_EXTRA, "lgb_reg_20d_36")
    # 配对检验（同天）
    a = pd.read_csv(BASE / "daily_ic_lgb_reg_20d_31.csv").set_index("date")["rank_ic"]
    b = pd.read_csv(BASE / "daily_ic_lgb_reg_20d_36.csv").set_index("date")["rank_ic"]
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    tt = stats.ttest_rel(j.iloc[:, 1], j.iloc[:, 0])
    wins = int((j.iloc[:, 1] > j.iloc[:, 0]).sum())
    print(f"\n配对检验 36 vs 31: 差={float((j.iloc[:,1]-j.iloc[:,0]).mean()):+.4f}  "
          f"t={tt.statistic:+.2f}  p={tt.pvalue:.4f}  ({len(j)} 天, 36胜 {wins} 天)", flush=True)
    out = {"trained_at": time.strftime("%Y-%m-%d %H:%M:%S"), "model_31": r31, "model_36": r36,
           "pair_36_vs_31": {"diff": float((j.iloc[:, 1] - j.iloc[:, 0]).mean()),
                             "nw_t": float(tt.statistic), "p": float(tt.pvalue),
                             "days": int(len(j)), "wins_36": wins,
                             "extra_feats": V4D_EXTRA}}
    json.dump(out, open(BASE / "train_20d_v36_results.json", "w"), indent=1, ensure_ascii=False)
    print(f"完成 总耗时 {time.time()-t0:.0f}s  →  {BASE}")
