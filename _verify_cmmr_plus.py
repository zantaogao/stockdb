"""实证：fusion_score_cmmr（CMMR+）与 reg10 的相关性（8/3-8/7）
若 CMMR+ 不含 reg10 → 相关性应≈0；若受影响 → 相关性显著"""
import sqlite3
import numpy as np
from scipy.stats import spearmanr

state = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
for sd in ('20260803', '20260804', '20260805', '20260806', '20260807'):
    rows = state.execute("""
        SELECT reg10, cmmr_score, fusion_score_cmmr, ma40_slope, fusion_score
        FROM signal_history WHERE REPLACE(date,'-','') = ?
          AND fusion_score_cmmr IS NOT NULL AND reg10 IS NOT NULL
    """, (sd,)).fetchall()
    r10 = np.array([r[0] for r in rows])
    cmmr_plus = np.array([r[2] for r in rows])
    old_score = np.array([r[1] for r in rows])
    slope = np.array([r[3] for r in rows])
    fusion = np.array([r[4] for r in rows])
    print(f'{sd}: n={len(rows)}')
    print(f'  corr(fusion_score_cmmr, reg10)   = {spearmanr(cmmr_plus, r10)[0]:+.4f}  <- 关键')
    print(f'  corr(cmmr_score, reg10)          = {spearmanr(old_score, r10)[0]:+.4f}')
    print(f'  corr(fusion_score_cmmr, ma40斜率)= {spearmanr(cmmr_plus, slope)[0]:+.4f}')
    print(f'  corr(fusion_score_cmmr, fusion)  = {spearmanr(cmmr_plus, fusion)[0]:+.4f}')
    print(f'  corr(fusion_score(主账户), reg10) = {spearmanr(fusion, r10)[0]:+.4f}')
state.close()
