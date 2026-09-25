#!/usr/bin/env python3
"""LSTM推理 v2 — 使用lstm_v2.pt + 全期因子表"""
import os, json, duckdb, numpy as np, torch
from torch import nn

MODEL = r'C:\Users\pumma\factor_lib\lstm_v2.pt'
DB = r'C:\Users\pumma\factor_lib\stock.db'
OUT = r'C:\Users\pumma\factor_lib'

YME = 0.0054
YSD = 0.0645

class Model(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(8, 128, 2, batch_first=True, dropout=0.3)
        self.fc = nn.Sequential(nn.Linear(128, 64), nn.ReLU(), nn.Dropout(0.3), nn.Linear(64, 1))
    def forward(self, x):
        o, _ = self.lstm(x)
        return self.fc(o[:, -1, :])

dev = 'cuda' if torch.cuda.is_available() else 'cpu'
m = Model()
m.load_state_dict(torch.load(MODEL, map_location=dev))
m.to(dev); m.eval()
print(f"Loaded ({dev})", flush=True)

core = ['mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20']
con = duckdb.connect(DB, read_only=True)
dt = con.execute("SELECT MAX(date) FROM factor_daily_values WHERE date > '2000-01-01'").fetchone()[0]
print(f"最新因子日期: {dt}", flush=True)

df = con.execute(f"""
    SELECT stock_code, date, factor_name, zscore
    FROM factor_daily_values
    WHERE date >= DATE '{dt}' - INTERVAL '30' DAY
      AND factor_name IN ({','.join(f"'{c}'" for c in core)})
      AND zscore IS NOT NULL
    ORDER BY stock_code, date
""").fetchdf()
con.close()

pv = df.pivot_table(index=['stock_code','date'], columns='factor_name', values='zscore').reset_index()
pv = pv.sort_values(['stock_code','date'])

res = {}
for code, grp in pv.groupby('stock_code'):
    grp = grp.sort_values('date')
    filled = grp[core].ffill().bfill().dropna()
    v = filled.values.astype(np.float32)
    if len(v) < 20:
        v = np.vstack([np.zeros((20-len(v), 8), dtype=np.float32), v])
    else:
        v = v[-20:]
    with torch.no_grad():
        p = m(torch.tensor(v[None,:,:]).to(dev)).item()
    res[code] = round(p * YSD + YME, 6)

top = sorted(res.items(), key=lambda x: -x[1])
print(f"{len(res)} stocks")
for code, p in top[:15]:
    print(f"  {code}: {p*100:+.2f}%")

with open(os.path.join(OUT, 'lstm_pred.json'), 'w') as f:
    json.dump(res, f, ensure_ascii=False)
print("Done")
