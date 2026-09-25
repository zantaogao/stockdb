#!/usr/bin/env python3
"""LSTM推理 — 每日调用，输出各股预测收益"""
import os, sys, json, duckdb, numpy as np, torch
from datetime import date
from torch import nn

MODEL_PATH = os.path.expanduser('~/.hermes/stockdb/models/lstm_final.pt')
DB_PATH = os.path.expanduser('~/.hermes/stockdb/stock_pc.db')
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.expanduser('~/.hermes/stockdb/stock.db')
if not os.path.exists(DB_PATH):
    DB_PATH = r'C:\Users\pumma\factor_lib\stock.db'

# LSTM模型结构（必须与训练时一致）
class LSTMPredictor(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(8, 128, 2, batch_first=True, dropout=0.3)
        self.fc = nn.Sequential(nn.Linear(128, 64), nn.ReLU(), nn.Dropout(0.3), nn.Linear(64, 1))
    def forward(self, x):
        o, _ = self.lstm(x)
        return self.fc(o[:, -1, :])

# 加载模型
device = 'cuda' if torch.cuda.is_available() else 'cpu'
model = LSTMPredictor()
model.load_state_dict(torch.load(MODEL_PATH, map_location=device))
model.to(device)
model.eval()
print(f"LSTM模型已加载 (device={device})", flush=True)

def predict_stocks(codes=None, date=None):
    """批量预测多只股票
    
    Args:
        codes: 股票代码列表，None=全部
        date: 目标日期，None=最新
    
    Returns:
        dict: {stock_code: pred_return}
    """
    con = duckdb.connect(DB_PATH, read_only=True)
    
    if date is None:
        date = con.execute("SELECT MAX(date) FROM factor_daily_values WHERE date > '2000-01-01'").fetchone()[0]
    
    # 取因子数据
    core = ['mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20']
    
    if codes:
        codes_str = ','.join(f"'{c}'" for c in codes)
        filter_sql = f"AND f.stock_code IN ({codes_str})"
    else:
        filter_sql = ""
    
    df = con.execute(f"""
        SELECT f.stock_code, f.date, f.factor_name, f.zscore
        FROM factor_daily_values f
        WHERE f.date BETWEEN DATE '{date}' - 30 AND '{date}'
          AND f.factor_name IN ({','.join(f"'{c}'" for c in core)})
          AND f.zscore IS NOT NULL
          {filter_sql}
        ORDER BY f.stock_code, f.date
    """).fetchdf()
    con.close()
    
    if df.empty:
        print("无数据", flush=True)
        return {}
    
    # 透视成宽表
    pivot = df.pivot_table(index=['stock_code', 'date'], columns='factor_name', values='zscore').reset_index()
    pivot = pivot.sort_values(['stock_code', 'date'])
    
    # 逐股票取最近20天
    results = {}
    for code, grp in pivot.groupby('stock_code'):
        grp = grp.dropna(subset=core)
        vals = grp[core].values.astype(np.float32)
        if len(vals) < 20:
            # 不足20天则填充0
            pad = np.zeros((20 - len(vals), 8), dtype=np.float32)
            vals = np.vstack([pad, vals])
        else:
            vals = vals[-20:]
        
        # 推理
        with torch.no_grad():
            tensor = torch.tensor(vals[None, :, :]).to(device)
            pred = model(tensor).item()
        
        results[code] = round(float(pred), 6)
    
    return results


if __name__ == '__main__':
    # 测试：预测最新日期
    import time
    t0 = time.time()
    preds = predict_stocks()
    elapsed = time.time() - t0
    
    # 输出前10只
    sorted_preds = sorted(preds.items(), key=lambda x: -x[1])
    print(f"\n预测前10 (共{len(preds)}只, 耗时{elapsed:.1f}s):")
    print(f"  {'代码':<8} {'预测收益':<12}")
    print(f"  {'-'*20}")
    for code, pred in sorted_preds[:10]:
        print(f"  {code:<8} {pred*100:+.2f}%")
    
    # 保存到文件
    out_path = os.path.expanduser(f'~/.hermes/stockdb/lstm_pred_{str(date.today())}.json')
    with open(out_path, 'w') as f:
        json.dump(preds, f, ensure_ascii=False)
    print(f"\n已保存: {out_path}")
