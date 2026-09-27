import sys, numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data
import duckdb, pandas as pd
conn = duckdb.connect('tushare.db', read_only=True)
idx_data = load_index_data()
# 旧样本 f17-22 真实含义：600508 20260910 手工枚举 38 维全部候选
code='600508'; ts='600508.SH'
rows = conn.execute(f"SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount FROM daily WHERE ts_code='{ts}' ORDER BY trade_date").fetchall()
closes=[float(r[1]) for r in rows]; highs=[float(r[3]) for r in rows]; lows=[float(r[4]) for r in rows]
pcts=[float(r[5])/100 for r in rows]; vols=[float(r[6]) for r in rows]; dates=[str(r[0]) for r in rows]
adj = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",[ts]).fetchall()
ac,ah,al = apply_forward_adjust(closes,highs,lows,adj)
i = dates.index('20260910')
info = idx_data.get(get_board_index(code))
idx_c = info['dict'] if info else None
# 空 val_dict → compute_features 兜底 0.5/0.5/22（与旧 build 传占位 0.5 不同！）
f38 = compute_features(ac[i-60:i+1],ah[i-60:i+1],al[i-60:i+1],vols[i-60:i+1],pcts[i-60:i+1],idx_c,{})
PV=[0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
f31=[float(f38[j]) for j in PV]
print('f31[17-22] =', [round(v,4) for v in f31[17:23]])
old = pd.read_parquet('analysis/retrain_10d_v4/samples_v4.parquet')
row = old[(old.code==code)&(old.date=='2026-09-10')]
print('旧样本 f17-22 =', row[['f17','f18','f19','f20','f21','f22']].values[0].tolist())
print('idx_c:', None if idx_c is None else idx_c[-1])
