#!/usr/bin/env python3
"""
双模型训练：回归（连续值） + 分类（硬阈值>5%）
对比 IC / 准确率 / 夏普
"""
import duckdb, os, json, sys, numpy as np, lightgbm as lgb
from sklearn.metrics import accuracy_score, roc_auc_score, mean_squared_error
from scipy.stats import spearmanr

DB_PATH = os.path.expanduser('~/.hermes/stockdb/stock.db')
MODEL_DIR = os.path.expanduser('~/.hermes/stockdb/models')
os.makedirs(MODEL_DIR, exist_ok=True)

conn = duckdb.connect(DB_PATH, read_only=True)

THRESHOLD = 5.0  # 硬阈值：未来20日涨超5%

# 采样股票（成交额TOP200）
codes = [r[0] for r in conn.execute("""
    SELECT stock_code FROM (
        SELECT stock_code, SUM(amount) as amt FROM stock_daily 
        WHERE date >= '2025-01-01' GROUP BY stock_code ORDER BY amt DESC LIMIT 200
    ) t
""").fetchall()]

print(f"采样股票: {len(codes)} 只")

features_list, labels_reg, labels_cls = [], [], []
row_info = []  # (code, date)

for code in codes:
    rows = conn.execute(f"""
        SELECT date, close, COALESCE(change_pct,0), volume
        FROM stock_daily WHERE stock_code='{code}' ORDER BY date
    """).fetchall()
    if len(rows) < 140:
        continue
    
    for i in range(120, len(rows) - 20):
        hist = rows[i-120:i+1]
        closes = np.array([r[1] for r in hist])
        l_close = closes[-1]
        future_ret = (rows[i+20][1] / l_close - 1) * 100
        
        # 20维特征
        chg5 = (l_close/closes[-5]-1)*100 if len(closes)>=5 else 0
        chg10 = (l_close/closes[-10]-1)*100 if len(closes)>=10 else 0
        chg20 = (l_close/closes[-20]-1)*100 if len(closes)>=20 else 0
        chg60 = (l_close/closes[-60]-1)*100 if len(closes)>=60 else 0
        chg120 = (l_close/closes[0]-1)*100
        
        ma5 = np.mean(closes[-5:]) if len(closes)>=5 else l_close
        ma10 = np.mean(closes[-10:]) if len(closes)>=10 else l_close
        ma20 = np.mean(closes[-20:]) if len(closes)>=20 else l_close
        ma60 = np.mean(closes[-60:]) if len(closes)>=60 else l_close
        ma120 = np.mean(closes)
        
        d5 = (l_close/ma5-1)*100; d10 = (l_close/ma10-1)*100
        d20 = (l_close/ma20-1)*100; d60 = (l_close/ma60-1)*100
        d120 = (l_close/ma120-1)*100
        
        bull1 = 1 if ma5 > ma10 > ma20 else 0
        bull2 = 1 if ma20 > ma60 else 0
        
        r20 = max(closes[-20:]) - min(closes[-20:])
        rr = r20/min(closes[-20:])*100 if min(closes[-20:])>0 else 0
        std20 = np.std(closes[-20:])/np.mean(closes[-20:])*100
        
        vols = np.array([r[3] for r in hist[-20:]])
        vr = vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
        
        rl, rh = min(closes[-20:]), max(closes[-20:])
        pos = (l_close-rl)/(rh-rl)*100 if rh!=rl else 50
        nh = 1 if l_close > rh*0.97 else 0
        
        vpc = 1 if chg5>0 and vr>1.2 else 0
        c1d = rows[i][2] or 0
        c3d = (l_close/closes[-3]-1)*100 if len(closes)>=3 else 0
        
        feat = np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
                         bull1,bull2,rr,std20,vr,pos,nh,vpc,c1d,c3d], dtype=np.float32)
        
        features_list.append(feat)
        labels_reg.append(future_ret)
        labels_cls.append(1 if future_ret > THRESHOLD else 0)
        row_info.append((code, str(rows[i][0])))

X = np.array(features_list)
y_reg = np.array(labels_reg, dtype=np.float32)
y_cls = np.array(labels_cls, dtype=np.int32)

print(f"总样本: {len(X)}")
print(f"回归目标: 均值{y_reg.mean():+.2f}% 中位数{np.median(y_reg):+.2f}%")
print(f"分类正样本(>{THRESHOLD}%): {y_cls.mean()*100:.1f}%")

# 时间序列切分
split = int(len(X) * 0.8)
X_train, X_test = X[:split], X[split:]
yr_train, yr_test = y_reg[:split], y_reg[split:]
yc_train, yc_test = y_cls[:split], y_cls[split:]
info_test = row_info[split:]

print(f"\n训练集: {len(X_train):,}  测试集: {len(X_test):,}")

# === 回归模型 ===
print("\n" + "="*50)
print("训练回归模型...")
print("="*50)

reg_model = lgb.LGBMRegressor(
    n_estimators=500, learning_rate=0.05, max_depth=6,
    num_leaves=31, subsample=0.8, colsample_bytree=0.8,
    min_child_samples=20, random_state=42, verbose=-1
)
reg_model.fit(X_train, yr_train,
    eval_set=[(X_test, yr_test)],
    eval_metric=['rmse', 'mae'],
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])

# 回归评估
pred_reg = reg_model.predict(X_test)
rmse = np.sqrt(mean_squared_error(yr_test, pred_reg))
mae = np.mean(np.abs(pred_reg - yr_test))
ic, _ = spearmanr(pred_reg, yr_test)

print(f"  回归 RMSE: {rmse:.2f}%")
print(f"  回归 MAE: {mae:.2f}%")
print(f"  Rank IC: {ic:.4f}")

# 用回归预测做模拟交易：预测收益最高的10% vs 最低的10%
top_pct = 10
n_top = max(len(pred_reg)//top_pct, 10)
top_idx = np.argsort(pred_reg)[-n_top:]
bot_idx = np.argsort(pred_reg)[:n_top]
top_ret = np.mean(yr_test[top_idx])
bot_ret = np.mean(yr_test[bot_idx])
print(f"  预测TOP{top_pct}%实际收益: {top_ret:+.2f}%")
print(f"  预测BOT{top_pct}%实际收益: {bot_ret:+.2f}%")
print(f"  多空收益差: {top_ret-bot_ret:+.2f}%")

# 按预测值分组看实际收益
print(f"\n  回归预测分组收益:")
sorted_idx = np.argsort(pred_reg)
n_groups = 10
for g in range(n_groups):
    start = g * len(sorted_idx) // n_groups
    end = (g+1) * len(sorted_idx) // n_groups
    grp_idx = sorted_idx[start:end]
    actual = np.mean(yr_test[grp_idx])
    pred = np.mean(pred_reg[grp_idx])
    print(f"    组{g+1}: 预测{pred:+.1f}% → 实际{actual:+.1f}%")

# === 分类模型 ===
print("\n" + "="*50)
print(f"训练分类模型（阈值>{THRESHOLD}%）...")
print("="*50)

cls_model = lgb.LGBMClassifier(
    n_estimators=500, learning_rate=0.05, max_depth=6,
    num_leaves=31, subsample=0.8, colsample_bytree=0.8,
    min_child_samples=20, class_weight='balanced',
    random_state=42, verbose=-1
)
cls_model.fit(X_train, yc_train,
    eval_set=[(X_test, yc_test)],
    eval_metric=['auc', 'binary_logloss'],
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])

# 分类评估
pred_cls = cls_model.predict(X_test)
prob_cls = cls_model.predict_proba(X_test)[:, 1]
acc = accuracy_score(yc_test, pred_cls)
auc = roc_auc_score(yc_test, prob_cls)

# 分类的实际收益
pos_idx = prob_cls > 0.5
neg_idx = prob_cls <= 0.5
if np.sum(pos_idx) > 10:
    pos_ret = np.mean(yr_test[pos_idx])
    neg_ret = np.mean(yr_test[neg_idx])
else:
    pos_ret, neg_ret = 0, 0

print(f"  准确率: {acc*100:.2f}%")
print(f"  AUC: {auc:.4f}")
print(f"  预测涨(>50%概率)实际收益: {pos_ret:+.2f}%")
print(f"  预测跌实际收益: {neg_ret:+.2f}%")
print(f"  多空收益差: {pos_ret-neg_ret:+.2f}%")

# 特征重要性
print(f"\n  分类特征TOP10:")
imp = cls_model.feature_importances_
names = ['chg5','chg10','chg20','chg60','chg120','d5','d10','d20','d60','d120',
         'bull1','bull2','range','std20','vol_r','pos','near_h','vpc','c1d','c3d']
pairs = sorted(zip(names, imp), key=lambda x: x[1], reverse=True)
for n, v in pairs[:10]:
    print(f"    {n:8s} {v}")

# === 对比结论 ===
print(f"\n{'='*50}")
print("对比结论")
print(f"{'='*50}")
print(f"\n{'指标':20s} {'回归':>12s} {'分类(>5%)':>12s}")
print(f"{'─'*44}")
print(f"{'IC(Rank IC)':20s} {ic:>12.4f} {'N/A':>12s}")
print(f"{'准确率':20s} {'N/A':>12s} {acc*100:>11.2f}%")
print(f"{'AUC':20s} {'N/A':>12s} {auc:>12.4f}")
print(f"{'多空收益差':20s} {top_ret-bot_ret:>+11.2f}% {pos_ret-neg_ret:>+11.2f}%")
print(f"{'预测涨收益':20s} {top_ret:>+11.2f}% {pos_ret:>+11.2f}%")
print(f"{'预测跌收益':20s} {bot_ret:>+11.2f}% {neg_ret:>+11.2f}%")

# 保存模型
reg_model.booster_.save_model(os.path.join(MODEL_DIR, 'lgb_reg_model.txt'))
# 注意：此分类器仅20特征，不可覆盖27特征的部署版cls27
cls_model.booster_.save_model(os.path.join(MODEL_DIR, 'lgb_cls_20feat_dual_only.txt'))
print(f"\n✅ 模型已保存至: {MODEL_DIR}/")

conn.close()
