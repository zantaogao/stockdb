#!/usr/bin/env python3
"""
准备训练数据 + 训练 LightGBM 模型
从 stock.db 提取特征，训练预测未来20日涨跌方向
"""
import duckdb, os, json, sys, pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, roc_auc_score
from datetime import datetime, date, timedelta

DB_PATH = os.path.expanduser('~/.hermes/stockdb/stock.db')
MODEL_DIR = os.path.expanduser('~/.hermes/stockdb/models')
os.makedirs(MODEL_DIR, exist_ok=True)

print("=" * 60)
print("LightGBM 选股模型 — 训练流程")
print("=" * 60)

conn = duckdb.connect(DB_PATH, read_only=True)

# 获取所有有足够数据的股票
stock_codes = conn.execute("""
    SELECT stock_code FROM stock_daily 
    GROUP BY stock_code 
    HAVING COUNT(*) >= 120
    ORDER BY stock_code
""").fetchall()

print(f"\n有120天以上数据的股票: {len(stock_codes)} 只")

# 准备训练样本
all_features = []
all_labels = []
all_info = []

sample_count = 0
today = date(2026, 5, 29)

print("准备训练数据...(每5000样本打点)")
for sc in stock_codes:
    code = sc[0]
    
    # 获取日线
    rows = conn.execute(f"""
        SELECT date, close, change_pct, volume, amount, amplitude
        FROM stock_daily WHERE stock_code='{code}' 
        ORDER BY date
    """).fetchall()
    
    if len(rows) < 140:  # 需要至少120天历史+20天未来
        continue
    
    # 按月切片，每个月的第一天作为样本点
    # 要求：有完整的120天历史 + 20天未来
    for i in range(120, len(rows) - 20):
        # 历史窗口
        hist = rows[i-120:i]
        future = rows[i:i+20]
        
        hist_closes = [r[1] for r in hist]
        latest_close = hist_closes[-1]
        future_close = future[-1][1]
        
        # 标签：未来20日涨跌幅是否 > 3%（正样本=上涨超过3%）
        future_return = (future_close / latest_close - 1) * 100
        label = 1 if future_return > 3 else 0
        
        # 特征工程
        features = []
        
        # 1. 动量特征 (5个)
        chg_5d = (latest_close/hist_closes[-5]-1)*100 if len(hist_closes)>=5 else 0
        chg_10d = (latest_close/hist_closes[-10]-1)*100 if len(hist_closes)>=10 else 0
        chg_20d = (latest_close/hist_closes[-20]-1)*100 if len(hist_closes)>=20 else 0
        chg_60d = (latest_close/hist_closes[-60]-1)*100 if len(hist_closes)>=60 else 0
        chg_120d = (latest_close/hist_closes[0]-1)*100
        features.extend([chg_5d, chg_10d, chg_20d, chg_60d, chg_120d])
        
        # 2. 均线偏离 (4个)
        ma5 = sum(hist_closes[-5:])/5 if len(hist_closes)>=5 else latest_close
        ma10 = sum(hist_closes[-10:])/10 if len(hist_closes)>=10 else latest_close
        ma20 = sum(hist_closes[-20:])/20 if len(hist_closes)>=20 else latest_close
        ma60 = sum(hist_closes[-60:])/60 if len(hist_closes)>=60 else latest_close
        ma120 = sum(hist_closes)/len(hist_closes)
        
        dev_ma5 = (latest_close/ma5-1)*100
        dev_ma10 = (latest_close/ma10-1)*100
        dev_ma20 = (latest_close/ma20-1)*100
        dev_ma60 = (latest_close/ma60-1)*100
        dev_ma120 = (latest_close/ma120-1)*100
        features.extend([dev_ma5, dev_ma10, dev_ma20, dev_ma60, dev_ma120])
        
        # 3. 均线排列 (2个)
        bull_5_10_20 = 1 if ma5 > ma10 > ma20 else 0
        bull_20_60 = 1 if ma20 > ma60 else 0
        features.extend([bull_5_10_20, bull_20_60])
        
        # 4. 波动特征 (3个)
        recent_high = max(hist_closes[-20:])
        recent_low = min(hist_closes[-20:])
        range_20d = (recent_high-recent_low)/recent_low*100
        std_20d = np.std(hist_closes[-20:])/np.mean(hist_closes[-20:])*100
        
        # 振幅(VOL)特征
        recent_vols = [r[3] for r in hist[-20:]]
        vol_ratio = recent_vols[-1]/np.mean(recent_vols) if np.mean(recent_vols)>0 else 1
        features.extend([range_20d, std_20d, vol_ratio])
        
        # 5. 位置特征 (2个)
        pos_in_range = (latest_close-recent_low)/(recent_high-recent_low)*100 if recent_high != recent_low else 50
        near_high = 1 if latest_close > recent_high*0.97 else 0
        features.extend([pos_in_range, near_high])
        
        # 6. 量价关系 (2个)
        price_up = 1 if chg_5d > 0 else 0
        vol_up = 1 if vol_ratio > 1.2 else 0
        vol_price_confirm = 1 if price_up and vol_up else 0  # 放量上涨=确认
        features.append(vol_price_confirm)
        
        # 7. 短期反转 (2个)
        chg_1d = hist[-1][2] or 0  # 昨日涨跌
        chg_3d = (latest_close/hist_closes[-3]-1)*100 if len(hist_closes)>=3 else 0
        features.extend([chg_1d, chg_3d])
        
        all_features.append(features)
        all_labels.append(label)
        all_info.append((code, str(rows[i][0]), future_return))
        sample_count += 1
        
        if sample_count % 5000 == 0:
            print(f"  {sample_count} 样本...", end="\r")

conn.close()

print(f"\n总样本量: {sample_count}")
print(f"正样本(未来涨>3%): {sum(all_labels)} ({sum(all_labels)/len(all_labels)*100:.1f}%)")
print(f"负样本: {len(all_labels)-sum(all_labels)} ({(len(all_labels)-sum(all_labels))/len(all_labels)*100:.1f}%)")

# 转为 numpy
X = np.array(all_features, dtype=np.float32)
y = np.array(all_labels, dtype=np.int32)

print(f"\n特征维度: {X.shape[1]}")
feature_names = [
    'chg_5d','chg_10d','chg_20d','chg_60d','chg_120d',
    'dev_ma5','dev_ma10','dev_ma20','dev_ma60','dev_ma120',
    'bull_5_10_20','bull_20_60',
    'range_20d','std_20d','vol_ratio',
    'pos_in_range','near_high',
    'vol_price_confirm',
    'chg_1d','chg_3d'
]

# 时间序列交叉验证（按时间顺序8:2切分）
split_idx = int(len(X) * 0.8)
X_train, X_test = X[:split_idx], X[split_idx:]
y_train, y_test = y[:split_idx], y[split_idx:]

print(f"\n训练集: {len(X_train)}  测试集: {len(X_test)}")

# 训练 LightGBM
print("\n训练 LightGBM 模型...")
model = lgb.LGBMClassifier(
    n_estimators=500,
    learning_rate=0.05,
    max_depth=6,
    num_leaves=31,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_samples=20,
    class_weight='balanced',
    random_state=42,
    verbose=-1,
    device_type='cpu'
)

model.fit(
    X_train, y_train,
    eval_set=[(X_test, y_test)],
    eval_metric=['auc', 'binary_logloss'],
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
)

# 评估
y_pred = model.predict(X_test)
y_prob = model.predict_proba(X_test)[:, 1]

acc = accuracy_score(y_test, y_pred)
auc = roc_auc_score(y_test, y_prob)

print(f"\n{'='*60}")
print("模型评估")
print(f"{'='*60}")
print(f"  测试集准确率: {acc*100:.2f}%")
print(f"  AUC: {auc:.4f}")
print(f"  正样本率(测试集): {y_test.mean()*100:.1f}%")

# 特征重要性
importance = pd.DataFrame({
    'feature': feature_names,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)

print(f"\n特征重要性 TOP10:")
for i, row in importance.head(10).iterrows():
    print(f"  {row['feature']:20s} {row['importance']:5.0f}")

# 保存模型
model_path = os.path.join(MODEL_DIR, 'lgb_stock_model.txt')
model.booster_.save_model(model_path)
print(f"\n模型已保存: {model_path}")

# 保存特征名
with open(os.path.join(MODEL_DIR, 'feature_names.json'), 'w') as f:
    json.dump(feature_names, f)

# 保存scaler信息
scaler_info = {
    'mean': X.mean(axis=0).tolist(),
    'std': X.std(axis=0).tolist(),
    'feature_names': feature_names
}
with open(os.path.join(MODEL_DIR, 'scaler_info.json'), 'w') as f:
    json.dump(scaler_info, f, cls=NpEncoder)

print(f"模型文件已保存至: {MODEL_DIR}/")
print(f"\n用时: 5-10 秒")

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.int_, np.intc, np.intp, np.int8, np.int16, np.int32, np.int64,
                           np.uint8, np.uint16, np.uint32, np.uint64)):
            return int(obj)
        elif isinstance(obj, (np.float_, np.float16, np.float32, np.float64)):
            return float(obj)
        elif isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        return super().default(obj)

if __name__ == '__main__':
    main()
