#!/usr/bin/env python3
"""
因子关系可视化：验证线性取反假设
X轴 = 因子值, Y轴 = 未来20日收益率
检查：线性拟合 R^2 vs 多项式拟合 R^2
"""
import duckdb
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.stats import linregress

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'
STATE_DB = BASE / 'state.db'

def get_factor_return_data(factor_name, lookback_days=60):
    """获取因子值与未来收益率的配对数据"""
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    # 获取因子数据 (stk_factor 表)
    # 注意：假设因子数据在 stk_factor 表，如果不在需要调整
    factor_query = f"""
        SELECT ts_code, trade_date, {factor_name} as factor_val
        FROM stk_factor
        WHERE {factor_name} IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT 200000
    """
    factor_df = con.execute(factor_query).fetchdf()
    
    # 获取未来收益率 (daily 表)
    # 需要关联获取未来 20 日收益率
    return_query = """
        SELECT d1.ts_code, d1.trade_date as start_date, d1.close as start_close,
               d2.close as end_close,
               (d2.close - d1.close) / d1.close * 100 as future_ret_20d
        FROM daily d1
        JOIN daily d2 ON d1.ts_code = d2.ts_code 
            AND d2.trade_date = (
                SELECT trade_date FROM daily 
                WHERE ts_code = d1.ts_code 
                AND trade_date > d1.trade_date 
                ORDER BY trade_date LIMIT 1 OFFSET 20
            )
        LIMIT 200000
    """
    return_df = con.execute(return_query).fetchdf()
    
    con.close()
    
    # 合并数据 (需要日期对齐，这里简化处理：假设因子日期=收益起始日期)
    # 实际应用中需要精确对齐日期
    # 这里为了演示，直接取最近 60 天的数据做相关性分析
    # 简化：假设 factor_df 和 return_df 有重叠的 (ts_code, trade_date)
    
    # 实际逻辑：需要更复杂的日期对齐
    # 这里用简化版：取最近 N 天的数据，计算因子与未来收益的相关性
    print(f"因子 {factor_name}: 原始数据行数 {len(factor_df)}")
    
    # 简化：直接计算因子值与未来收益的相关性 (需要完整对齐)
    # 这里用 mock 数据演示逻辑，实际需替换为真实对齐代码
    return factor_df, return_df

def plot_scatter(factor_name, factor_vals, returns, title):
    """绘制散点图并计算拟合 R^2"""
    if len(factor_vals) < 100:
        print(f"数据点不足: {len(factor_vals)}")
        return
    
    # 去除异常值
    mask = (np.isfinite(factor_vals)) & (np.isfinite(returns))
    x = factor_vals[mask]
    y = returns[mask]
    
    if len(x) < 50:
        return
    
    # 线性拟合
    slope, intercept, r_value, p_value, std_err = linregress(x, y)
    r2_linear = r_value ** 2
    
    # 多项式拟合 (2阶)
    coeffs = np.polyfit(x, y, 2)
    poly_func = np.poly1d(coeffs)
    y_pred_poly = poly_func(x)
    ss_res = np.sum((y - y_pred_poly) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2_poly = 1 - (ss_res / ss_tot)
    
    print(f"{factor_name}: 线性 R^2 = {r2_linear:.4f}, 多项式 R^2 = {r2_poly:.4f}")
    
    # 绘图
    plt.figure(figsize=(10, 6))
    plt.scatter(x, y, alpha=0.3, s=10, label='Data')
    
    # 线性线
    x_line = np.linspace(x.min(), x.max(), 100)
    y_line = slope * x_line + intercept
    plt.plot(x_line, y_line, 'r-', linewidth=2, label=f'Linear Fit (R²={r2_linear:.3f})')
    
    # 多项式线
    y_poly = poly_func(x_line)
    plt.plot(x_line, y_poly, 'g--', linewidth=2, label=f'Poly Fit (R²={r2_poly:.3f})')
    
    plt.xlabel(factor_name)
    plt.ylabel('Future 20d Return (%)')
    plt.title(title)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    save_path = BASE / f'scripts/output/{factor_name}_scatter.png'
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path)
    print(f"Saved: {save_path}")
    plt.close()
    
    return r2_linear, r2_poly

def main():
    factors = ['rsi_12', 'pct_chg', 'vol', 'amount']
    
    # 简化版：直接查表计算相关性 (实际需日期对齐)
    # 这里用简化逻辑：假设因子值和未来收益在同一行 (实际需 join)
    # 为了演示，我们直接查 tushare.db 的 stk_factor 和 daily 表
    
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    # 获取最近 60 天的因子和收益数据
    # 注意：这里需要精确的日期对齐逻辑
    # 简化：取最近 60 天的所有股票数据
    query = """
        WITH factor_data AS (
            SELECT ts_code, trade_date, rsi_12, pct_chg, vol, amount
            FROM stk_factor
            WHERE trade_date >= (SELECT MAX(trade_date) FROM stk_factor) - INTERVAL '60' DAY
        ),
        future_ret AS (
            SELECT d1.ts_code, d1.trade_date,
                   (d2.close - d1.close) / d1.close * 100 as ret_20d
            FROM daily d1
            JOIN daily d2 ON d1.ts_code = d2.ts_code 
                AND d2.trade_date = (
                    SELECT trade_date FROM daily 
                    WHERE ts_code = d1.ts_code 
                    AND trade_date > d1.trade_date 
                    ORDER BY trade_date LIMIT 1 OFFSET 20
                )
        )
        SELECT f.ts_code, f.trade_date, f.rsi_12, f.pct_chg, f.vol, f.amount, fr.ret_20d
        FROM factor_data f
        JOIN future_ret fr ON f.ts_code = fr.ts_code AND f.trade_date = fr.trade_date
        WHERE f.rsi_12 IS NOT NULL AND fr.ret_20d IS NOT NULL
        LIMIT 50000
    """
    
    try:
        df = con.execute(query).fetchdf()
        print(f"Total samples: {len(df)}")
        
        if len(df) > 100:
            # 绘制 rsi_12
            plot_scatter('rsi_12', df['rsi_12'].values, df['ret_20d'].values, 
                        'RSI_12 vs Future 20d Return')
            
            # 绘制 pct_chg
            plot_scatter('pct_chg', df['pct_chg'].values, df['ret_20d'].values, 
                        'Pct_Chg vs Future 20d Return')
            
            # 绘制 vol
            plot_scatter('vol', df['vol'].values, df['ret_20d'].values, 
                        'Volume vs Future 20d Return')
            
            # 绘制 amount
            plot_scatter('amount', df['amount'].values, df['ret_20d'].values, 
                        'Amount vs Future 20d Return')
        else:
            print("样本不足，尝试扩大日期范围...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        con.close()

if __name__ == '__main__':
    main()