#!/usr/bin/env python3
"""
每日预测脚本 — 用已训练的 LightGBM 模型预测候选股未来20日涨跌概率
盘后运行，输出融合到多因子评分中
"""
import duckdb, os, json, sys, numpy as np, lightgbm as lgb

DB_PATH = os.path.expanduser('~/.hermes/stockdb/stock.db')
MODEL_DIR = os.path.expanduser('~/.hermes/stockdb/models')
HOLD_PATH = os.path.expanduser('~/.hermes/stockdb/holdings.json')

MODEL_FILE = os.path.join(MODEL_DIR, 'lgb_stock_model.txt')
FEATURES_FILE = os.path.join(MODEL_DIR, 'feature_names.json')

def get_features(conn, code):
    """为单只股票生成20维特征向量"""
    rows = conn.execute(f"""
        SELECT date, close, change_pct, volume
        FROM stock_daily WHERE stock_code='{code}' 
        ORDER BY date DESC LIMIT 120
    """).fetchall()
    
    if not rows or len(rows) < 120:
        return None
    
    rows = rows[::-1]  # 正序
    closes = [r[1] for r in rows]
    l_close = closes[-1]
    
    # 动量
    chg_5d = (l_close/closes[-5]-1)*100
    chg_10d = (l_close/closes[-10]-1)*100
    chg_20d = (l_close/closes[-20]-1)*100
    chg_60d = (l_close/closes[-60]-1)*100
    chg_120d = (l_close/closes[0]-1)*100
    
    # 均线偏离
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:])
    ma120 = np.mean(closes)
    dev_ma5 = (l_close/ma5-1)*100
    dev_ma10 = (l_close/ma10-1)*100
    dev_ma20 = (l_close/ma20-1)*100
    dev_ma60 = (l_close/ma60-1)*100
    dev_ma120 = (l_close/ma120-1)*100
    
    # 排列
    bull_5_10_20 = 1 if ma5 > ma10 > ma20 else 0
    bull_20_60 = 1 if ma20 > ma60 else 0
    
    # 波动
    recent_high = max(closes[-20:])
    recent_low = min(closes[-20:])
    range_20d = (recent_high-recent_low)/recent_low*100
    std_20d = np.std(closes[-20:])/np.mean(closes[-20:])*100
    
    recent_vols = [r[3] for r in rows[-20:]]
    vol_ratio = recent_vols[-1]/np.mean(recent_vols) if np.mean(recent_vols)>0 else 1
    
    # 位置
    pos_in_range = (l_close-recent_low)/(recent_high-recent_low)*100 if recent_high != recent_low else 50
    near_high = 1 if l_close > recent_high*0.97 else 0
    
    # 量价
    price_up = 1 if chg_5d > 0 else 0
    vol_up = 1 if vol_ratio > 1.2 else 0
    vol_price_confirm = 1 if price_up and vol_up else 0
    
    # 短期
    chg_1d = rows[-1][2] or 0
    chg_3d = (l_close/closes[-3]-1)*100 if len(closes)>=3 else 0
    
    return np.array([
        chg_5d, chg_10d, chg_20d, chg_60d, chg_120d,
        dev_ma5, dev_ma10, dev_ma20, dev_ma60, dev_ma120,
        bull_5_10_20, bull_20_60,
        range_20d, std_20d, vol_ratio,
        pos_in_range, near_high,
        vol_price_confirm,
        chg_1d, chg_3d
    ], dtype=np.float32)

def main():
    if not os.path.exists(MODEL_FILE):
        print(f"❌ 模型文件不存在: {MODEL_FILE}")
        print("请先运行: python3 scripts/train_lgb_model.py")
        return
    
    print("加载 LightGBM 模型...")
    model = lgb.Booster(model_file=MODEL_FILE)
    
    conn = duckdb.connect(DB_PATH, read_only=True)
    
    with open(HOLD_PATH) as f:
        data = json.load(f)
    
    # 预测所有 watch_active + watch_cold + hold
    targets = [p for p in data['positions'] 
               if p.get('status') in ('watch_active', 'watch_cold', 'hold') 
               and not p['code'].startswith('TRUST')]
    
    print(f"\n预测 {len(targets)} 只候选股...")
    predictions = []
    
    for p in targets:
        code = p['code']
        name = p['name']
        status = p['status']
        
        features = get_features(conn, code)
        if features is None:
            continue
        
        prob = model.predict(features.reshape(1, -1))[0]
        
        # 获取当前价和月表现
        latest = conn.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}' 
            ORDER BY date DESC LIMIT 1
        """).fetchone()
        price = latest[0] if latest else 0
        
        may_first = conn.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}' 
            AND date >= '2026-05-01' ORDER BY date LIMIT 1
        """).fetchone()
        may_chg = (price/may_first[0]-1)*100 if may_first else 0
        
        # 年线偏离
        ma120_data = conn.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}' 
            ORDER BY date DESC LIMIT 120
        """).fetchall()
        if ma120_data:
            ma120 = np.mean([r[0] for r in ma120_data])
            dev120 = (price/ma120-1)*100
        else:
            dev120 = 0
        
        predictions.append((prob, code, name, price, may_chg, dev120, status))
    
    # 按模型概率排序
    predictions.sort(key=lambda r: r[0], reverse=True)
    
    print(f"\n{'='*65}")
    print("LightGBM 候选股排序（预测未来20日上涨概率）")
    print(f"{'='*65}")
    print(f"{'排名':>4} {'代码':6s} {'名称':8s} {'预测涨概率':>10s} {'现价':>8s} {'5月%':>7s} {'年线偏':>7s} {'状态':12s}")
    print(f"{'─'*65}")
    
    for i, r in enumerate(predictions, 1):
        prob, code, name, price, may_chg, dev120, status = r
        prob_str = f"{prob*100:5.1f}%"
        bar = "█" * int(prob * 20) + "░" * (20 - int(prob * 20))
        status_short = status.replace('watch_', '')
        print(f"{i:>4} {code:6s} {name:8s} {bar} {prob_str}  {price:>7.2f} {may_chg:>+6.1f}% {dev120:>+6.0f}% {status_short:12s}")
    
    conn.close()
    
    print(f"\n结论:")
    high_conf = [r for r in predictions if r[0] > 0.6]
    mid_conf = [r for r in predictions if 0.45 <= r[0] <= 0.6]
    low_conf = [r for r in predictions if r[0] < 0.45]
    
    if high_conf:
        print(f"\n🟢 高置信度(>60%) — {len(high_conf)}只:")
        for r in high_conf:
            print(f"  {r[2]:8s} {r[1]:6s}  {r[0]*100:.0f}%  年线偏{r[5]:+.0f}%")
    
    if mid_conf:
        print(f"\n🟡 中等置信度(45-60%) — {len(mid_conf)}只:")
        for r in mid_conf:
            print(f"  {r[2]:8s} {r[1]:6s}  {r[0]*100:.0f}%  年线偏{r[5]:+.0f}%")
    
    if low_conf:
        print(f"\n🔴 低置信度(<45%) — {len(low_conf)}只:")
        for r in low_conf:
            print(f"  {r[2]:8s} {r[1]:6s}  {r[0]*100:.0f}%  年线偏{r[5]:+.0f}%")

if __name__ == '__main__':
    main()
