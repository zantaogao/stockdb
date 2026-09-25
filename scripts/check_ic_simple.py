#!/usr/bin/env python3
"""快速检查：原始因子 vs 取反因子 IC 对比"""
import duckdb
import numpy as np
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'

con = duckdb.connect(str(TUSHARE_DB), read_only=True)

# 获取最大日期
max_date_str = con.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0]
print(f"Max date: {max_date_str}")

# 转换为整数计算
max_date_int = int(max_date_str)
cutoff_date = max_date_int - 100

# 查询数据
query = f"""
    SELECT ts_code, trade_date, rsi_12, pct_chg, vol, amount
    FROM stk_factor
    WHERE CAST(trade_date AS INTEGER) >= {cutoff_date}
    AND rsi_12 IS NOT NULL
    LIMIT 50000
"""
df_factor = con.execute(query).fetchdf()
print(f"Factor samples: {len(df_factor)}")

# 获取未来收益
query_ret = f"""
    SELECT d1.ts_code, d1.trade_date as start_date, d1.close as start_close,
           d2.close as end_close,
           (d2.close - d1.close) / d1.close * 100 as ret_20d
    FROM daily d1
    JOIN daily d2 ON d1.ts_code = d2.ts_code 
        AND d2.trade_date = (
            SELECT trade_date FROM daily 
            WHERE ts_code = d1.ts_code 
            AND trade_date > d1.trade_date 
            ORDER BY trade_date LIMIT 1 OFFSET 20
        )
    WHERE CAST(d1.trade_date AS INTEGER) >= {cutoff_date}
    LIMIT 50000
"""
df_ret = con.execute(query_ret).fetchdf()
print(f"Return samples: {len(df_ret)}")

# 合并
df = df_factor.merge(df_ret, left_on=['ts_code', 'trade_date'], right_on=['ts_code', 'start_date'], how='inner')
print(f"Merged samples: {len(df)}")

if len(df) < 1000:
    print("样本不足")
else:
    factors = ['rsi_12', 'pct_chg', 'vol', 'amount']
    print("\n=== 原始 vs 取反 IC 对比 ===")
    print(f"{'因子':<10} {'原始 IC':<12} {'取反 IC':<12} {'提升':<10}")
    print("-" * 50)
    for f in factors:
        mask = df[f].notna() & df['ret_20d'].notna()
        if mask.sum() > 100:
            orig_ic = np.corrcoef(df.loc[mask, f], df.loc[mask, 'ret_20d'])[0, 1]
            if f == 'rsi_12':
                inv_vals = 100 - df.loc[mask, f].values
            else:
                inv_vals = -df.loc[mask, f].values
            inv_ic = np.corrcoef(inv_vals, df.loc[mask, 'ret_20d'].values)[0, 1]
            print(f"{f:<10} {orig_ic:<12.4f} {inv_ic:<12.4f} {inv_ic-orig_ic:<10.4f}")

con.close()