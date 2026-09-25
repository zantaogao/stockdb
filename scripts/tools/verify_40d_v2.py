"""验证40d模型评分 - 27特征版"""
import sys, duckdb, numpy as np
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')

from core.scoring import score_stock, _ensure_models
from core.features import compute_raw_features, standardize_v9

_ensure_models()

con = duckdb.connect('/Users/zantao/.hermes/stockdb/stock.db', read_only=True)

for code, name in [('002837', '英维克'), ('000001', '平安银行'), ('600519', '贵州茅台')]:
    rows = con.execute("""
        SELECT date, close, open, high, low, change_pct, volume, amount
        FROM stock_daily WHERE stock_code=? ORDER BY date DESC LIMIT 200
    """, [code]).fetchall()
    print(f'\n=== {name}({code}) ===')
    print(f'最新: {rows[0][0]} close={rows[0][1]:.2f}')
    result = score_stock(code, rows)
    if result:
        print(f'  40d预测: {result.get("reg40_pred", "N/A")}')
        print(f'  20d(reg_pred): {result.get("reg_pred", "N/A")}%')
        print(f'  综合评分: {result.get("final_score", "N/A")}')
        print(f'  fusion_avg: {result.get("fusion_avg", "N/A")}')
        print(f'  cls27: {result.get("cls27_prob", "N/A")}')
    
    # 手动验证40d能predict成功
    from core.scoring import _V9_REG40, _V9_STATS40
    base_raw, dt_str = compute_raw_features(code, rows, con)
    if base_raw is not None and _V9_REG40 is not None and _V9_STATS40:
        feat40 = base_raw[:23].copy()
        feat40[20] = 0.5; feat40[21] = 0.5; feat40[22] = 22.0
        feat40_s = standardize_v9(feat40, _V9_STATS40)
        feat40_full = np.append(feat40_s, [0, 0, 0, 0])  # no GTJA, use zeros
        pred40 = _V9_REG40.predict(feat40_full.reshape(1, -1))[0]
        print(f'  手动40d预测: {pred40:.4f} ({(pred40+10)/50*100:.1f}分)')
        print(f'  特征数: {feat40_full.shape[0]} (期望27)')

con.close()
print('\n=== 全部验证完成 ===')
