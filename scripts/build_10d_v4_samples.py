"""构建 10d v4 重训样本（Mac 侧，只拼样本不训练）
口径与 train_10d_v3.py 完全一致：
  - 股票池: stock_basic 排除北交所/ST/退/8-4-92开头
  - 日线从 tushare.db daily 读全历史(>=2022-01-01), adj_factor 前复权
  - feat_tushare.compute_features 38维 → 取 PV_INDICES 31维（索引与 scoring.py 推理侧逐位一致）
  - y = T+10 前复权收盘 / T 收盘 - 1
  - 输出: analysis/retrain_10d_v4/samples_v4.parquet (date, code, f0..f30, y)
"""
import sys, os, time
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(os.path.expanduser('~/.hermes/stockdb'))
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / 'scripts'))
from core.db import get_tushare_db
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data

FEAT_WIN, FWD_DAYS = 60, 10
SAMPLE_START = os.environ.get('SAMPLE_START', '2022-01-01')
OUT_NAME = os.environ.get('OUT_NAME', 'samples_v4.parquet')
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
# 与 train_10d_v3/scoring.py 推理侧一致(31个索引, 命名为f0..f30)
N_FEATS = len(PV_INDICES)

conn = get_tushare_db()
stocks = []
for symbol, name, list_date in conn.execute("SELECT symbol, name, list_date FROM stock_basic WHERE market != '北交所'").fetchall():
    if name and ('ST' in name or 'st' in name or '退' in name): continue
    if symbol.startswith(('8','4','92')): continue
    stocks.append(symbol)
print(f'股票池: {len(stocks)}', flush=True)

idx_data = load_index_data()
rows_out = []
t0 = time.time()
for ci, code in enumerate(stocks):
    ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    rows = conn.execute(f"""
        SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
        FROM daily WHERE ts_code='{ts_code}' AND trade_date >= '{SAMPLE_START.replace('-','')}'
        ORDER BY trade_date""").fetchall()
    if len(rows) < FEAT_WIN + FWD_DAYS + 10: continue
    closes = [float(r[1]) for r in rows]; highs = [float(r[3]) for r in rows]
    lows = [float(r[4]) for r in rows]; pcts = [float(r[5])/100.0 for r in rows]
    vols = [float(r[6]) for r in rows]
    dates = [str(r[0])[:10] if '-' in str(r[0]) else f'{str(r[0])[:4]}-{str(r[0])[4:6]}-{str(r[0])[6:8]}' for r in rows]
    adj_rows = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date", [ts_code]).fetchall()
    ac, ah, al = apply_forward_adjust(closes, highs, lows, adj_rows)
    board = get_board_index(code)
    idx_info = idx_data.get(board)
    val_dict = {'ep': 0.5, 'bp': 0.5, 'ln_cap': 22.0}
    for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
        idx_dict = None
        if idx_info:
            idx_dict = {d: v for d, v in idx_info['dict'].items() if d <= dates[i]}
        feat38 = compute_features(ac[i-FEAT_WIN:i+1], ah[i-FEAT_WIN:i+1], al[i-FEAT_WIN:i+1],
                                  vols[i-FEAT_WIN:i+1], pcts[i-FEAT_WIN:i+1],
                                  idx_dict, val_dict)
        if feat38 is None: continue
        y = ac[i+FWD_DAYS] / ac[i] - 1
        rows_out.append([dates[i], code] + [feat38[j] for j in PV_INDICES] + [y])
    if (ci+1) % 500 == 0:
        print(f'  {ci+1}/{len(stocks)}  {len(rows_out):,} 样本  {time.time()-t0:.0f}s', flush=True)
conn.close()

cols = ['date','code'] + [f'f{j}' for j in range(N_FEATS)] + ['y']
df = pd.DataFrame(rows_out, columns=cols)
out = BASE / 'analysis/retrain_10d_v4'
out.mkdir(parents=True, exist_ok=True)
df.to_parquet(out / OUT_NAME, index=False)
print(f'完成: {len(df):,} 行 → {out}/{OUT_NAME}  ({(out/OUT_NAME).stat().st_size/1e6:.0f} MB)')
print(f'日期范围: {df.date.min()} ~ {df.date.max()}')
print(f'标签: mean={df.y.mean()*100:+.4f}% std={df.y.std()*100:.3f}% range=[{df.y.min()*100:.1f}%, {df.y.max()*100:.1f}%]')