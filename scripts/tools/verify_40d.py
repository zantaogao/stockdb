"""验证40d模型评分"""
import sys, duckdb, numpy as np
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')

from core.features import compute_raw_features, standardize_v5, get_gtja_signals, standardize_v9
from core.scoring import score_stock, _ensure_models

# 加载模型
_ensure_models()

# 英维克数据
con = duckdb.connect('/Users/zantao/.hermes/stockdb/stock.db', read_only=True)
rows = con.execute("""
    SELECT date, close, open, high, low, change_pct, volume, amount
    FROM stock_daily WHERE stock_code='002837' ORDER BY date DESC LIMIT 200
""").fetchall()
print(f'英维克最新: close={rows[0][1]:.2f}, 日期={rows[0][0]}')

# 用compute_raw_features算特征 + standardize_v9标准化（40d用）
code = '002837'
base_raw, dt_str = compute_raw_features(code, rows, con)
if base_raw is not None:
    print(f'特征维度: {len(base_raw)}')
    from core.scoring import _V9_REG40, _V9_STATS40
    if _V9_REG40 is not None:
        feat_v9 = standardize_v9(base_raw, _V9_STATS40)
        feat_v9_full = np.append(feat_v9, [0, 0, 0, 0])
        pred40 = _V9_REG40.predict(feat_v9_full.reshape(1, -1))[0]
        print(f'40d预测: {pred40:.6f} ({pred40*100:.2f}%)')
    else:
        print('40d模型未加载！')
else:
    print('特征计算失败')

# 也试完整评分
result = score_stock(code, rows)
if result:
    print(f'完整评分: {result}')

con.close()
print('验证完成')
