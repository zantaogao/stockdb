# 10d v6 新口径样本: 只重算ex5/10/20(f23/24/25), 其余维复制旧样本
# 逐票: daily全历史+adj→逐日60票窗口(同build i循环)→compute_features新ex(个股日历回看)
import sys, time, numpy as np, pandas as pd, duckdb
sys.path.insert(0,'/Users/zantao/.hermes/stockdb'); sys.path.insert(0,'/Users/zantao/.hermes/stockdb/scripts')
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data

BASE='/Users/zantao/.hermes/stockdb/analysis/retrain_20260926'
SAMPLES=pd.read_parquet(BASE+'/samples_10d.parquet')
SAMPLES['date']=SAMPLES['date'].astype(str).str.replace('-','',regex=False)
codes=sorted(SAMPLES['code'].unique())
print('样本', len(SAMPLES), '票数', len(codes), flush=True)

con=duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
idx_data=load_index_data()
FEAT_WIN=59

def dash(d):  # 20260924 -> 2026-09-24
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if '-' not in d else d

def recompute_ex(code):
    ts=code+'.SH' if code.startswith(('6','68','9')) else (code+'.BJ' if code.startswith('9') else code+'.SZ')
    if code.startswith('9'): ts=code+'.BJ'
    rows=con.execute(f"SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol FROM daily WHERE ts_code='{ts}' ORDER BY trade_date").fetchall()
    if len(rows)<FEAT_WIN+1: return {}
    dates=[str(r[0]) for r in rows]
    closes=[float(r[1]) for r in rows]; highs=[float(r[2]) for r in rows]; lows=[float(r[3]) for r in rows]
    pcts=[float(r[4])/100.0 for r in rows]; vols=[float(r[5]) for r in rows]
    af=con.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",[ts]).fetchall()
    ac,ah,al=apply_forward_adjust(closes,highs,lows,af)
    board=idx_data.get(get_board_index(code))
    if board is None: return {}
    idx_full=dict(zip(board['dates'], [board['dict'][dd] for dd in board['dates']]))
    out={}
    for i in range(FEAT_WIN, len(rows)):
        d=dates[i]
        win_dates=[dash(x) for x in dates[i-FEAT_WIN:i+1]]  # 与idx键同格式
        f=compute_features(ac[i-FEAT_WIN:i+1],ah[i-FEAT_WIN:i+1],al[i-FEAT_WIN:i+1],vols[i-FEAT_WIN:i+1],pcts[i-FEAT_WIN:i+1],idx_full,{},dates=win_dates)
        out[d]=(float(f[23]),float(f[24]),float(f[25]))
    return out

t0=time.time()
by_code={c:g.index.values for c,g in SAMPLES.groupby('code')}
new_e5=np.full(len(SAMPLES), np.nan); new_e10=np.full(len(SAMPLES), np.nan); new_e20=np.full(len(SAMPLES), np.nan)
miss=0; done=0
for k,c in enumerate(codes):
    exd=recompute_ex(c)
    idxs=by_code[c]; dts=SAMPLES.loc[idxs,'date'].values
    for idx,d in zip(idxs,dts):
        v=exd.get(d)
        if v is None: miss+=1; v=(0.0,0.0,0.0)
        new_e5[idx],new_e10[idx],new_e20[idx]=v
    done+=1
    if done%250==0:
        el=time.time()-t0
        print(f'{done}/{len(codes)} {el:.0f}s eta {el/done*(len(codes)-done):.0f}s', flush=True)
        tmp=SAMPLES.copy(); tmp['f23']=new_e5; tmp['f24']=new_e10; tmp['f25']=new_e20
        tmp.to_parquet(BASE+'/samples_10d_v6_partial.parquet')

new=SAMPLES.copy()
assert np.isnan(new_e5).sum()==0, f'残留NaN {np.isnan(new_e5).sum()}'
new['f23']=new_e5; new['f24']=new_e10; new['f25']=new_e20
new.to_parquet(BASE+'/samples_10d_v6.parquet')
print('DONE miss(样本日无ex)=%d 耗时%.0fs'%(miss,time.time()-t0), flush=True)
for j in (23,24,25):
    print(f"f{j}: 旧口径 mean/std={SAMPLES[f'f{j}'].mean():.4f}/{SAMPLES[f'f{j}'].std():.4f}  新口径 mean/std={new[f'f{j}'].mean():.4f}/{new[f'f{j}'].std():.4f}", flush=True)
