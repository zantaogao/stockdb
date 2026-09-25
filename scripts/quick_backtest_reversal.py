#!/usr/bin/env python3
"""
快速回测：对比原始因子 vs 取反因子的效果
指标：IC, ICIR, 胜率, 夏普比率
"""
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'

def calculate_metrics(factor_vals, returns):
    """计算 IC, ICIR, 胜率"""
    mask = np.isfinite(factor_vals) & np.isfinite(returns)
    x = factor_vals[mask]
    y = returns[mask]
    
    if len(x) < 30:
        return None, None, None
    
    # IC (相关系数)
    ic = np.corrcoef(x, y)[0, 1]
    
    # ICIR (IC / IC 标准差) - 需要滚动计算，这里简化
    ic_ir = ic / (np.std(x) + 1e-8)  # 简化版
    
    # 胜率 (因子值高时，收益高的比例)
    # 将因子值分为十分位，看最高十分位 vs 最低十分位的胜率
    quantiles = pd.qcut(pd.Series(x), 10, duplicates='drop', labels=False)
    top_decile_ret = y[quantiles == 9].mean()
    bot_decile_ret = y[quantiles == 0].mean()
    win_rate = (top_decile_ret > bot_decile_ret)  # 简化：1 或 0
    
    # 更准确的胜率：计算因子值与收益同号的比例
    sign_match = np.sign(x - np.mean(x)) == np.sign(y - np.mean(y))
    win_rate = np.mean(sign_match) * 100
    
    return ic, ic_ir, win_rate

def main():
    factors = ['rsi_12', 'pct_chg', 'vol', 'amount']
    
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    # 获取最近 120 天数据 (足够计算 IC)
    query = """
        WITH factor_data AS (
            SELECT ts_code, trade_date, rsi_12, pct_chg, vol, amount
            FROM stk_factor
            WHERE trade_date >= (SELECT MAX(trade_date) FROM stk_factor) - INTERVAL '120' DAY
            AND rsi_12 IS NOT NULL
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
        LIMIT 100000
    """
    
    try:
        df = con.execute(query).fetchdf()
        print(f"总样本数: {len(df)}")
        
        if len(df) < 1000:
            print("样本不足")
            return
        
        print("\n=== 原始因子 vs 取反因子 效果对比 ===")
        print(f"{'因子':<12} {'原始 IC':<10} {'原始胜率':<12} {'取反 IC':<10} {'取反胜率':<12} {'提升':<8}")
        print("-" * 70)
        
        results = []
        
        for factor in factors:
            original_vals = df[factor].values
            returns = df['ret_20d'].values
            
            # 原始因子
            ic_orig, icir_orig, win_orig = calculate_metrics(original_vals, returns)
            
            # 取反因子
            inverted_vals = -original_vals  # 或 100 - original_vals for RSI
            if factor == 'rsi_12':
                inverted_vals = 100 - original_vals
            
            ic_inv, icir_inv, win_inv = calculate_metrics(inverted_vals, returns)
            
            if ic_orig is not None and ic_inv is not None:
                improvement = ic_inv - ic_orig
                print(f"{factor:<12} {ic_orig:<10.4f} {win_orig:<12.1f} {ic_inv:<10.4f} {win_inv:<12.1f} {improvement:<8.4f}")
                results.append({
                    'factor': factor,
                    'orig_ic': ic_orig,
                    'orig_win': win_orig,
                    'inv_ic': ic_inv,
                    'inv_win': win_inv,
                    'improvement': improvement
                })
        
        # 总结
        print("\n=== 结论 ===")
        for r in results:
            if r['improvement'] > 0.1:
                print(f"✅ {r['factor']}: 取反后 IC 提升 {r['improvement']:.4f}，建议取反")
            elif r['improvement'] > 0:
                print(f"⚠️ {r['factor']}: 取反后 IC 微升 {r['improvement']:.4f}，可考虑取反")
            else:
                print(f"❌ {r['factor']}: 取反后 IC 下降 {r['improvement']:.4f}，保持原样")
        
        # 保存结果
        import json
        save_path = BASE / 'scripts/output/backtest_reversal.json'
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved: {save_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        con.close()

if __name__ == '__main__':
    main()