"""Evaluate saved LSTM v2 model (load + final eval only)"""
import duckdb, numpy as np, pandas as pd, torch, time, os, json
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from scipy import stats

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
t0 = time.time()

con = duckdb.connect(DB)
raw = con.execute("""
    SELECT f.date, f.stock_code, f.factor_name, f.zscore,
           (b.close / a.close - 1) as ret_future
    FROM factor_daily_values f
    JOIN stock_daily a ON f.stock_code = a.stock_code AND f.date = a.date
    LEFT JOIN stock_daily b ON f.stock_code = b.stock_code 
        AND b.date = (SELECT MIN(date) FROM stock_daily 
                      WHERE stock_code = f.stock_code AND date > f.date + 4)
    WHERE f.zscore IS NOT NULL AND f.date >= '2024-03-01'
      AND f.factor_name IN ('mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20')
    ORDER BY f.stock_code, f.date
""").fetchdf()
con.close()

core = ['mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20']
pv = raw.pivot_table(index=['stock_code','date','ret_future'],
                     columns='factor_name', values='zscore').reset_index()
pv = pv.sort_values(['stock_code','date']).dropna(subset=core)
pv = pv.dropna(subset=['ret_future'] + core)

seqs, tgts = [], []
for code, grp in pv.groupby('stock_code'):
    grp = grp.sort_values('date')
    v = grp[core].values.astype(np.float32)
    r = grp['ret_future'].values.astype(np.float32)
    for i in range(20, len(grp)):
        if not np.isnan(v[i-20:i]).any() and not np.isnan(r[i]):
            seqs.append(v[i-20:i]); tgts.append(r[i])

X = np.array(seqs); y = np.array(tgts)
split = int(len(X) * 0.80)
X_te = X[split:]; y_te = y[split:]
yme, ysd = np.mean(y[:split]), np.std(y[:split]) + 1e-8

tel = DataLoader(TensorDataset(torch.tensor(X_te), torch.tensor((y_te - yme) / ysd)), 512, shuffle=False)
print(f"测试集: {len(y_te):,}", flush=True)

class LSTMPredictor(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(8, 128, 2, batch_first=True, dropout=0.3)
        self.fc = nn.Sequential(nn.Linear(128, 64), nn.ReLU(), nn.Dropout(0.3), nn.Linear(64, 1))
    def forward(self, x):
        o, _ = self.lstm(x); return self.fc(o[:, -1, :])

m = LSTMPredictor().to(DEVICE)
m.load_state_dict(torch.load(os.path.join(OUT, "lstm_v2.pt"))); m.eval()

pp_list = []
with torch.no_grad():
    for Xb, _ in tel:
        pp_list.append(m(Xb.to(DEVICE)).cpu().numpy().flatten())
pp_f = np.concatenate(pp_list) * ysd + yme

ic_f = stats.spearmanr(pp_f, y_te)[0]
print(f"LSTM v2 IC={ic_f:.4f}", flush=True)

print(f"\nLSTM分组 (测试集, {len(y_te):,}):")
sorted_idx = np.argsort(pp_f)
for g in range(10):
    s = g * len(sorted_idx) // 10
    e = (g+1) * len(sorted_idx) // 10
    grp = sorted_idx[s:e]
    print(f"组{g+1:2d}: 预测{np.mean(pp_f[grp]):+.2%} -> 实际{np.mean(y_te[grp]):+.2%}", flush=True)

results = {'lstm_ic': round(ic_f, 4), 'lstm_seqs': len(X), 'lstm_test': len(y_te)}
print(f"\n{json.dumps(results, indent=2)}", flush=True)
with open(os.path.join(OUT, "lstm_v2_results.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"耗时: {time.time()-t0:.0f}s", flush=True)
