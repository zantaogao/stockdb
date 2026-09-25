#!/usr/bin/env python3
"""
滚动 IC 分析：检查因子 IC 随时间的变化趋势
判断：因子是否稳定有效，还是风格切换
"""
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import timedelta

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'

def calculate_ic(factor_vals, returns):
    """计算 IC (因子值与未来收益的相关系数)"""
    mask = np.isfinite(factor_vals) & np.isfinite(returns)
    if np.sum(mask) < 30:
        return np.nan
    return np.corrcoef(factor_vals[mask], returns[mask])[0, 1]

def main():
    factors = ['rsi_12', 'pct_chg', 'vol', 'amount']
    window_days = 60  # 滚动窗口 60 天
    
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    # 获取所有因子数据和未来收益
    query = """
        WITH factor_data AS (
            SELECT ts_code, trade_date, rsi_12, pct_chg, vol, amount
            FROM stk_factor
            WHERE rsi_12 IS NOT NULL
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
        SELECT f.trade_date, f.rsi_12, f.pct_chg, f.vol, f.amount, fr.ret_20d
        FROM factor_data f
        JOIN future_ret fr ON f.ts_code = fr.ts_code AND f.trade_date = fr.trade_date
        WHERE fr.ret_20d IS NOT NULL
        ORDER BY f.trade_date DESC
        LIMIT 500000
    """
    
    try:
        df = con.execute(query).fetchdf()
        print(f"总样本数: {len(df)}")
        
        if len(df) < window_days * 10:
            print("样本不足，可能需要扩大日期范围")
        
        # 按日期分组计算滚动 IC
        dates = sorted(df['trade_date'].unique())
        print(f"日期范围: {dates[0]} 到 {dates[-1]}")
        
        rolling_ic = []
        
        for i in range(len(dates) - window_days):
            end_date = dates[i + window_days - 1]
            start_date = dates[i]
            
            # 获取窗口内数据
            mask = (df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)
            window_df = df[mask]
            
            if len(window_df) < window_days * 5:  # 至少需要一定样本
                continue
            
            # 计算每个因子的 IC
            ic_data = {'date': end_date}
            for factor in factors:
                ic = calculate_ic(window_df[factor].values, window_df['ret_20d'].values)
                ic_data[factor] = ic
            
            rolling_ic.append(ic_data)
        
        if len(rolling_ic) < 10:
            print("滚动窗口数据不足")
            return
        
        ic_df = pd.DataFrame(rolling_ic)
        
        print("\n=== 滚动 IC 统计 (最近 60 天) ===")
        for factor in factors:
            recent_ic = ic_df[factor].tail(30).mean()
            all_ic = ic_df[factor].mean()
            std_ic = ic_df[factor].std()
            print(f"{factor}: 最近 30 天 IC={recent_ic:.3f}, 全期 IC={all_ic:.3f}, 波动={std_ic:.3f}")
        
        # 检查趋势
        print("\n=== IC 趋势判断 ===")
        for factor in factors:
            recent = ic_df[factor].tail(30).values
            if len(recent) < 20:
                continue
            
            # 简单线性趋势
            x = np.arange(len(recent))
            slope, _, _, _, _ = np.polyfit(x, recent, 1)
            
            if slope > 0.005:
                trend = "↑ 上升"
            elif slope < -0.005:
                trend = "↓ 下降"
            else:
                trend = "→ 稳定"
            
            print(f"{factor}: 趋势 {trend} (斜率={slope:.4f})")
        
        # 保存数据
        import json
        save_path = BASE / 'scripts/output/rolling_ic.json'
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 转换为列表格式保存
        ic_list = ic_df.to_dict('records')
        with open(save_path, 'w') as f:
            json.dump(ic_list, f, indent=2)
        print(f"\nSaved: {save_path}")
        
        # 简单绘图 (如果 matplotlib 可用)
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            
            plt.figure(figsize=(12, 6))
            for factor in factors:
                plt.plot(ic_df['date'].values, ic_df[factor].values, label=factor)
            
            plt.axhline(y=0, color='k', linestyle='--', alpha=0.3)
            plt.xlabel('Date')
            plt.ylabel('IC')
            plt.title('Rolling IC (60-day window)')
            plt.legend()
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            plot_path = BASE / 'scripts/output/rolling_ic.png'
            plt.savefig(plot_path)
            print(f"Saved plot: {plot_path}")
            plt.close()
        except Exception as e:
            print(f"绘图失败 (可能缺少 matplotlib): {e}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        con.close()

if __name__ == '__main__':
    main()