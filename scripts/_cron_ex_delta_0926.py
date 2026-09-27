"""ex 修复对拍（2026-09-26）：全市场新旧口径三模型分对比。
旧 = _load_idx_data 返回 {}（等价修复前生产 ex 恒 0）；新 = 修复后（ex 活值）。
判定预期：10d/20d 逐位 Δ=0（训练 ex std=0，模型不用）；40d Δ均值≈−0.5、|Δ|>1 约14%、top100重合≈91（历史测算）。
"""
import sys; sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts'); sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
import numpy as np, pandas as pd
import core.scoring as cs

conn = cs._safe_connect()
cs._load_models()
assert cs._reg10_model and cs._reg20_model and cs._reg40_model, '三模型未全部加载'

stocks = [r[0].split('.')[0] for r in conn.execute(
    "SELECT ts_code FROM stock_basic WHERE delist_date IS NULL ORDER BY ts_code").fetchall()]
print(f'市场 {len(stocks)} 只', flush=True)

_real_load = cs._load_idx_data
def run_mode(ex_off):
    cs._idx_data_cache = None
    cs._cs = sys.modules["core.scoring"]
    _cs._idx_data_cache = {} if ex_off else None
    _cs._load_idx_data = _real_load
    out = {}
    for i, code in enumerate(stocks):
        if (i + 1) % 1000 == 0: print(f'  mode={ex_off} {i+1}/{len(stocks)}', flush=True)
        s = cs.score_stock(code, conn=conn)
        if s is None: continue
        out[code] = (s.get('reg10_pred', 0.0), s.get('reg_pred', 0.0), s.get('reg40_pred', 0.0), s.get('fusion', 0.0))
    return out

print('旧口径（ex=0）...', flush=True)
old = run_mode(True)
print('新口径（ex 修复）...', flush=True)
new = run_mode(False)
cs._load_idx_data = _real_load
cs._idx_data_cache = None
conn.close()

common = sorted(set(old) & set(new))
print(f'共同股票 {len(common)}', flush=True)
df = pd.DataFrame({
    'code': common,
    'reg10_old': [old[c][0] for c in common], 'reg10_new': [new[c][0] for c in common],
    'reg20_old': [old[c][1] for c in common], 'reg20_new': [new[c][1] for c in common],
    'reg40_old': [old[c][2] for c in common], 'reg40_new': [new[c][2] for c in common],
    'fus_old': [old[c][3] for c in common], 'fus_new': [new[c][3] for c in common],
})
for tag in ['reg10', 'reg20', 'reg40', 'fus']:
    d = df[f'{tag}_new'] - df[f'{tag}_old']
    n_nonzero = int((d.abs() > 1e-9).sum())
    print(f'{tag}: Δ均值={d.mean():+.4f} 中位={d.median():+.4f} |Δ|>1只数={n_nonzero} ({n_nonzero/len(df)*100:.1f}%) '
          f'ρ={df[f"{tag}_old"].corr(df[f"{tag}_new"], method="spearman"):.4f}')
# top100 重合
for tag in ['reg40', 'fus']:
    t_old = set(df.nlargest(100, f'{tag}_old')['code']); t_new = set(df.nlargest(100, f'{tag}_new')['code'])
    print(f'{tag} top100 重合 = {len(t_old & t_new)}/100')
df.to_parquet('/Users/zantao/.hermes/stockdb/analysis/retrain_20260926/ex_delta_0926.parquet')
print('落盘 analysis/retrain_20260926/ex_delta_0926.parquet')
