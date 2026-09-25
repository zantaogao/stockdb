"""
保存GTJA因子结果到pickle，传输到PC
"""
import os, pickle, duckdb, numpy as np, pandas as pd, importlib, time, json

HOME = os.path.expanduser('~')
DB = os.path.join(HOME, '.hermes/stockdb/stock.db')

GTJA_FACTORS = [
    ('gtja_150_inv', 150, True), ('gtja_158_inv', 158, True), ('gtja_159_inv', 159, True),
    ('gtja_167_inv', 167, True), ('gtja_175_inv', 175, True), ('gtja_187_inv', 187, True),
    ('gtja_184', 184, False), ('gtja_168', 168, False), ('gtja_189_inv', 189, True),
    ('gtja_147_inv', 147, True), ('gtja_151_inv', 151, True), ('gtja_145_inv', 145, True),
    ('gtja_161_inv', 161, True), ('gtja_177', 177, False), ('gtja_157', 157, False),
    ('gtja_144', 144, False), ('gtja_156', 156, False), ('gtja_185', 185, False),
    ('gtja_179_inv', 179, True), ('gtja_140', 140, False), ('gtja_042', 42, False),
    ('gtja_046', 46, False), ('gtja_083', 83, False), ('gtja_099', 99, False),
    ('gtja_041', 41, False), ('gtja_062', 62, False), ('gtja_034', 34, False),
    ('gtja_025', 25, False), ('gtja_016', 16, False), ('gtja_005', 5, False),
    ('gtja_049', 49, False), ('gtja_048', 48, False), ('gtja_032', 32, False),
    ('gtja_026', 26, False), ('gtja_008', 8, False), ('gtja_035', 35, False),
    ('gtja_038', 38, False), ('gtja_001', 1, False), ('gtja_006', 6, False),
]

con = duckdb.connect(DB)
df = con.execute("""
    SELECT stock_code, date, open, close, high, low, volume, amount,
           change_pct/100.0 as returns
    FROM stock_daily WHERE date >= '2024-01-01' ORDER BY date, stock_code
""").fetchdf()
con.close()

panel = {}
for col in ['open','close','high','low','volume','amount','returns']:
    panel[col] = df.pivot_table(index='date', columns='stock_code', values=col)
panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)
print(f"Panel: {panel['close'].shape}", flush=True)

results = {}
for fname, alpha_num, invert in GTJA_FACTORS:
    t1 = time.time()
    mod = importlib.import_module(f"src.factors.zoo.gtja191.alpha_{alpha_num:03d}")
    signal = mod.compute(panel)
    if invert: signal = -signal
    results[fname] = signal
    print(f"  {fname}: {time.time()-t1:.1f}s", flush=True)

# Save as pickle
out_path = os.path.join(HOME, '.hermes/stockdb/gtja_signals.pkl')
with open(out_path, 'wb') as f:
    pickle.dump(results, f, protocol=5)

import os
size = os.path.getsize(out_path)
print(f"Saved: {out_path} ({size/1024/1024:.0f}MB)", flush=True)
