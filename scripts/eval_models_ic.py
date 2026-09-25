#!/usr/bin/env python3
"""三模型滚动IC评估（使用 scoring 模块引用）"""
import sys, random
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes/stockdb'))

import duckdb
import numpy as np
from scipy import stats
from core.db import TUSHARE_DB_PATH
from core import scoring

N_SAMPLE = 200
HORIZON = 5

scoring._load_models()
src = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)

dates = [r[0] for r in src.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date ASC"
).fetchall()]
eval_dates = [d for d in dates if d > dates[-30]][:-5][-10:]
print(f'评估: {eval_dates[0]}~{eval_dates[-1]} ({len(eval_dates)}天)')

all_codes = [r[0] for r in src.execute(
    "SELECT ts_code FROM daily WHERE trade_date=(SELECT MAX(trade_date) FROM daily) AND ts_code NOT LIKE '%ST%'"
).fetchall()]
random.seed(42)
sample = random.sample(all_codes, min(N_SAMPLE, len(all_codes)))
print(f'样本: {len(sample)}')

conn = scoring._safe_connect()
results = {n: {'ics': []} for n in ['10', '20', '40']}

for dt in eval_dates:
    fwd_rows = src.execute(f"""
        SELECT a.ts_code, (b.close / a.close - 1) as ret
        FROM daily a JOIN (
            SELECT ts_code, trade_date, close,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date) as rn
            FROM daily WHERE trade_date > '{dt}'
        ) b ON a.ts_code = b.ts_code AND b.rn = {HORIZON}
        WHERE a.trade_date = '{dt}'
    """).fetchall()
    fwd = {r[0]: float(r[1]) for r in fwd_rows if r[1] is not None}
    if len(fwd) < 50:
        continue

    scores = {n: {} for n in ['10', '20', '40']}
    for code in sample:
        base = code.replace('.SH','').replace('.SZ','')
        try:
            feat = scoring._compute_ml_features(base, conn, as_of_date=dt)
            if feat is None:
                continue
            for name in ['10', '20', '40']:
                mdl = getattr(scoring, f'_reg{name}_model')
                stats_key = getattr(scoring, f'_stats{name}')
                if mdl is None or stats_key is None:
                    continue
                if name == '10':
                    f = np.zeros(35)
                    f[:29] = feat
                else:
                    f = feat.copy()
                X = scoring._standardize(f, stats_key)
                scores[name][code] = float(mdl.predict(X.reshape(1, -1))[0])
        except Exception:
            pass

    for name in ['10', '20', '40']:
        common = set(scores[name].keys()) & set(fwd.keys())
        if len(common) < 30:
            continue
        sv = [scores[name][c] for c in common]
        rv = [fwd[c] for c in common]
        rho, _ = stats.spearmanr(sv, rv)
        results[name]['ics'].append(rho)

    r10 = results['10']['ics'][-1] if results['10']['ics'] else 0
    r20 = results['20']['ics'][-1] if results['20']['ics'] else 0
    r40 = results['40']['ics'][-1] if results['40']['ics'] else 0
    n_fwd = len(fwd)
    print(f'  {dt}: n={n_fwd:>4d}  10d={r10:+.4f}  20d={r20:+.4f}  40d={r40:+.4f}')

conn.close()
src.close()

print('\n' + '=' * 55)
print('三模型滚动IC评估')
print('=' * 55)
for name, label in [('10', '10d'), ('20', '20d'), ('40', '40d')]:
    ics = results[name]['ics']
    if not ics:
        print(f'{label}: 无数据')
        continue
    m = float(np.mean(ics))
    s = float(np.std(ics, ddof=1)) if len(ics) > 1 else 0
    icir = m / s if s > 0 else 0
    wr = sum(1 for v in ics if v > 0) / len(ics)
    print(f'\n{label} ({len(ics)}天):')
    print(f'  IC均值={m:+.4f}  ICIR={icir:+.2f}')
    print(f'  胜率={wr:.0%}')
    print(f'  范围=[{min(ics):+.4f}, {max(ics):+.4f}]')
