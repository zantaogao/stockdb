"""LSTM v2 — 只跑LSTM部分（LightGBM已跑完）"""
import duckdb, numpy as np, pandas as pd, torch, time, os, json
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from scipy import stats

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
t0 = time.time()

print("=" * 60, flush=True)
print("LSTM v2 (8因子序列->5日收益, 全期数据)", flush=True)
print("=" * 60, flush=True)

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

print(f"因子数据: {len(raw)}行", flush=True)

core = ['mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20']
pv = raw.pivot_table(index=['stock_code','date','ret_future'],
                     columns='factor_name', values='zscore').reset_index()
pv = pv.sort_values(['stock_code','date']).dropna(subset=core)
pv = pv.dropna(subset=['ret_future'] + core)
print(f"Pivot后: {len(pv)}行", flush=True)

seqs, tgts = [], []
for code, grp in pv.groupby('stock_code'):
    grp = grp.sort_values('date')
    v = grp[core].values.astype(np.float32)
    r = grp['ret_future'].values.astype(np.float32)
    for i in range(20, len(grp)):
        if not np.isnan(v[i-20:i]).any() and not np.isnan(r[i]):
            seqs.append(v[i-20:i])
            tgts.append(r[i])

X = np.array(seqs); y = np.array(tgts)
print(f"序列: {X.shape}, 目标: {y.shape}", flush=True)

split = int(len(X) * 0.80)
X_tr, X_te = X[:split], X[split:]
y_tr, y_te = y[:split], y[split:]

yme, ysd = np.mean(y_tr), np.std(y_tr) + 1e-8
y_tr_n = (y_tr - yme) / ysd
y_te_n = (y_te - yme) / ysd

tl = DataLoader(TensorDataset(torch.tensor(X_tr), torch.tensor(y_tr_n)), 512, shuffle=True)
tel = DataLoader(TensorDataset(torch.tensor(X_te), torch.tensor(y_te_n)), 512, shuffle=False)

print(f"训练: {len(y_tr):,}  测试: {len(y_te):,}", flush=True)
print(f"收益: mean={yme:.4f} std={ysd:.4f}", flush=True)

class LSTMPredictor(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(8, 128, 2, batch_first=True, dropout=0.3)
        self.fc = nn.Sequential(nn.Linear(128, 64), nn.ReLU(), nn.Dropout(0.3), nn.Linear(64, 1))
    def forward(self, x):
        o, _ = self.lstm(x)
        return self.fc(o[:, -1, :])

m = LSTMPredictor().to(DEVICE)
opt = torch.optim.AdamW(m.parameters(), lr=0.001, weight_decay=1e-5)
sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, patience=5, factor=0.5, min_lr=1e-5)
loss_fn = nn.MSELoss()

best_loss = float('inf')
patience = 0
print(f"参数: {sum(p.numel() for p in m.parameters()):,}", flush=True)

for ep in range(40):
    m.train(); trl = 0
    for Xb, yb in tl:
        Xb, yb = Xb.to(DEVICE), yb.to(DEVICE)
        p = m(Xb).squeeze(); l = loss_fn(p, yb)
        opt.zero_grad(); l.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step(); trl += l.item() * len(Xb)
    trl /= len(tl.dataset)

    m.eval(); tel_l = 0; pp, aa = [], []
    with torch.no_grad():
        for Xb, yb in tel:
            Xb, yb = Xb.to(DEVICE), yb.to(DEVICE)
            p = m(Xb).squeeze(); tel_l += loss_fn(p, yb).item() * len(Xb)
            pp.extend(p.cpu().numpy()); aa.extend(yb.cpu().numpy())
    tel_l /= len(tel.dataset)

    pp_r = np.array(pp) * ysd + yme
    aa_r = np.array(aa) * ysd + yme
    ic = stats.spearmanr(pp_r, aa_r)[0]
    sched.step(tel_l)

    if (ep+1) % 5 == 0 or ep == 0:
        print(f"E{ep+1:2d}: tr={trl:.6f} val={tel_l:.6f} IC={ic:.4f}", flush=True)

    if tel_l < best_loss:
        best_loss = tel_l; patience = 0
        torch.save(m.state_dict(), os.path.join(OUT, "lstm_v2.pt"))
    else:
        patience += 1
        if patience >= 8:
            print(f"Early stop @ E{ep+1}", flush=True); break

# Final evaluation with DataLoader (avoid OOM)
m.load_state_dict(torch.load(os.path.join(OUT, "lstm_v2.pt"))); m.eval()
pp_f_list = []
with torch.no_grad():
    for Xb, _ in tel:
        pp_batch = m(Xb.to(DEVICE)).cpu().numpy().flatten()
        pp_f_list.append(pp_batch)
pp_f = np.concatenate(pp_f_list) * ysd + yme
ic_f = stats.spearmanr(pp_f, y_te)[0]

print(f"\nLSTM分组 (测试集):")
sorted_idx = np.argsort(pp_f)
for g in range(10):
    s = g * len(sorted_idx) // 10
    e = (g+1) * len(sorted_idx) // 10
    grp = sorted_idx[s:e]
    print(f"组{g+1:2d}: 预测{np.mean(pp_f[grp]):+.2%} -> 实际{np.mean(y_te[grp]):+.2%}", flush=True)

print(f"\nLSTM v2 IC={ic_f:.4f}", flush=True)
print(f"序列: {len(X):,}, 训练: {len(y_tr):,}, 测试: {len(y_te):,}", flush=True)
print(f"耗时: {time.time()-t0:.0f}s", flush=True)
