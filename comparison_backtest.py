#!/usr/bin/env python3
"""
方案对比回测 - 优化版
- 方案A: 独立三因子策略（只用新因子，不用reg10）
- 方案B: 三因子 + reg10融合策略
- 对比基准: 纯reg10策略
"""

import duckdb
import numpy as np
import pandas as pd

# 初始化数据库连接
conn = duckdb.connect('state.db')
conn.execute("ATTACH '/Users/zantao/.hermes/stockdb/tushare.db' AS t2")

print("=" * 60)
print("方案对比回测")
print("=" * 60)

today = '2026-07-24'
one_year_ago = '2025-07-24'

# 1. 获取最新因子数据
print("\n=== 1. 获取最新因子数据 ===")
factor_data = conn.execute(f"""
    SELECT 
        nf.stock_code,
        nf.ma_decay,
        fa.flow_alpha,
        va.vol_adj,
        sh.reg10,
        sh.fusion_score
    FROM new_factors nf
    JOIN flow_alpha fa ON nf.stock_code = fa.stock_code AND REPLACE(nf.date, '-', '') = REPLACE(fa.date, '-', '')
    JOIN vol_adj va ON nf.stock_code = va.stock_code AND REPLACE(nf.date, '-', '') = REPLACE(va.date, '-', '')
    JOIN signal_history sh ON nf.stock_code = sh.stock_code AND REPLACE(nf.date, '-', '') = REPLACE(sh.date, '-', '')
    WHERE nf.date = '{today}'
""").fetchdf()

print(f"因子数据: {len(factor_data)}只股票")

# 计算各因子的分位数和阈值
ma_q25 = factor_data['ma_decay'].quantile(0.25)
ma_q75 = factor_data['ma_decay'].quantile(0.75)
flow_q25 = factor_data['flow_alpha'].quantile(0.25)
flow_q75 = factor_data['flow_alpha'].quantile(0.75)
vol_q25 = factor_data['vol_adj'].quantile(0.25)
vol_q75 = factor_data['vol_adj'].quantile(0.75)

print(f"\n因子阈值:")
print(f"  MA_decay: Q25={ma_q25:.3f}, Q75={ma_q75:.3f}")
print(f"  flow_alpha: Q25={flow_q25:.3f}, Q75={flow_q75:.3f}")
print(f"  vol_adj: Q25={vol_q25:.3f}, Q75={vol_q75:.3f}")
print(f"  reg10: <0.03看涨, >0.03看跌")

# 2. 获取股价数据（只选1000只股票）
print("\n=== 2. 获取股价数据 ===")
sample_stocks = factor_data['stock_code'].sample(min(1000, len(factor_data)), random_state=42).tolist()

price_data = conn.execute(f"""
    SELECT 
        stock_code,
        CAST(date AS DATE) as date,
        close
    FROM t2.stock_daily
    WHERE CAST(date AS DATE) >= '{one_year_ago}' AND CAST(date AS DATE) <= '{today}'
    AND stock_code IN ({','.join(["'"+s+"'" for s in sample_stocks])})
    ORDER BY stock_code, date
""").fetchdf()

price_data = price_data.sort_values(['stock_code', 'date'])
price_data['next_close'] = price_data.groupby('stock_code')['close'].shift(-1)
price_data['next_return'] = (price_data['next_close'] - price_data['close']) / price_data['close']
price_data['date_str'] = price_data['date'].astype(str)

print(f"股价数据: {len(price_data)}条")
print(f"股票数量: {price_data['stock_code'].nunique()}")

# 3. 合并因子数据
factor_data_sample = factor_data[factor_data['stock_code'].isin(sample_stocks)]
price_data = price_data.merge(
    factor_data_sample[['stock_code', 'ma_decay', 'flow_alpha', 'vol_adj', 'reg10']],
    on='stock_code', how='left'
)

# 4. 用向量化方法计算滚动分位数（优化版）
print("\n=== 3. 计算滚动分位数 ===")
window = 20

def rolling_quantile_vectorized(df, col, window=20):
    """向量化计算滚动分位数"""
    result = pd.Series(np.nan, index=df.index)
    
    for stock in df['stock_code'].unique():
        mask = df['stock_code'] == stock
        stock_idx = df[mask].index
        stock_values = df.loc[stock_idx, col].values
        
        if len(stock_values) < window:
            result.loc[stock_idx] = np.nanpercentile(stock_values, [25, 75])[0] if len(stock_values) > 0 else np.nan
            continue
        
        # 计算滚动分位数
        for i in range(window, len(stock_values)):
            window_data = stock_values[i-window:i]
            result.iloc[stock_idx[i]] = np.nanpercentile(window_data, 25) if i % 2 == 0 else np.nan  # 每隔一天计算一次，加速
    
    return result

# 为每只股票计算滚动Q25和Q75
print("计算MA_decay滚动分位数...")
for stock in price_data['stock_code'].unique():
    mask = price_data['stock_code'] == stock
    stock_df = price_data.loc[mask].sort_values('date')
    if len(stock_df) < window:
        continue
    values = stock_df['ma_decay'].values
    q25_vals = [np.nanpercentile(values[max(0,i-window):i], 25) for i in range(len(values))]
    q75_vals = [np.nanpercentile(values[max(0,i-window):i], 75) for i in range(len(values))]
    
    # 填充前window天为全局分位数
    q25_vals[:window] = [ma_q25] * window
    q75_vals[:window] = [ma_q75] * window
    
    price_data.loc[mask, 'ma_q25'] = q25_vals
    price_data.loc[mask, 'ma_q75'] = q75_vals

print("计算flow_alpha滚动分位数...")
for stock in price_data['stock_code'].unique():
    mask = price_data['stock_code'] == stock
    stock_df = price_data.loc[mask].sort_values('date')
    if len(stock_df) < window:
        continue
    values = stock_df['flow_alpha'].values
    q25_vals = [np.nanpercentile(values[max(0,i-window):i], 25) for i in range(len(values))]
    q75_vals = [np.nanpercentile(values[max(0,i-window):i], 75) for i in range(len(values))]
    
    q25_vals[:window] = [flow_q25] * window
    q75_vals[:window] = [flow_q75] * window
    
    price_data.loc[mask, 'flow_q25'] = q25_vals
    price_data.loc[mask, 'flow_q75'] = q75_vals

print("计算vol_adj滚动分位数...")
for stock in price_data['stock_code'].unique():
    mask = price_data['stock_code'] == stock
    stock_df = price_data.loc[mask].sort_values('date')
    if len(stock_df) < window:
        continue
    values = stock_df['vol_adj'].values
    q25_vals = [np.nanpercentile(values[max(0,i-window):i], 25) for i in range(len(values))]
    q75_vals = [np.nanpercentile(values[max(0,i-window):i], 75) for i in range(len(values))]
    
    q25_vals[:window] = [vol_q25] * window
    q75_vals[:window] = [vol_q75] * window
    
    price_data.loc[mask, 'vol_q25'] = q25_vals
    price_data.loc[mask, 'vol_q75'] = q75_vals

print(f"滚动分位数计算完成")

# 5. 定义三个策略
print("\n=== 4. 定义策略 ===")

def strategy_A_only_factors(row):
    """方案A: 独立三因子策略"""
    ma_signal = 1 if pd.notna(row['ma_decay']) and row['ma_decay'] > row['ma_q75'] else (-1 if pd.notna(row['ma_decay']) and row['ma_decay'] < row['ma_q25'] else 0)
    flow_signal = 1 if pd.notna(row['flow_alpha']) and row['flow_alpha'] > row['flow_q75'] else (-1 if pd.notna(row['flow_alpha']) and row['flow_alpha'] < row['flow_q25'] else 0)
    vol_signal = 1 if pd.notna(row['vol_adj']) and row['vol_adj'] < row['vol_q25'] else (-1 if pd.notna(row['vol_adj']) and row['vol_adj'] > row['vol_q75'] else 0)
    
    score = ma_signal + flow_signal + vol_signal
    
    if score >= 2:
        return pd.Series({'position': 1, 'signal_type': '强买', 'score': score})
    elif score == 1:
        return pd.Series({'position': 1, 'signal_type': '买', 'score': score})
    elif score == 0:
        return pd.Series({'position': 0, 'signal_type': '持', 'score': score})
    elif score == -1:
        return pd.Series({'position': -1, 'signal_type': '卖', 'score': score})
    else:
        return pd.Series({'position': -1, 'signal_type': '强卖', 'score': score})

def strategy_B_combined(row):
    """方案B: 三因子+reg10融合策略"""
    reg_signal = -1 if pd.notna(row['reg10']) and row['reg10'] < 0.03 else (1 if pd.notna(row['reg10']) and row['reg10'] > 0.03 else 0)
    ma_signal = 1 if pd.notna(row['ma_decay']) and row['ma_decay'] > row['ma_q75'] else (-1 if pd.notna(row['ma_decay']) and row['ma_decay'] < row['ma_q25'] else 0)
    flow_signal = 1 if pd.notna(row['flow_alpha']) and row['flow_alpha'] > row['flow_q75'] else (-1 if pd.notna(row['flow_alpha']) and row['flow_alpha'] < row['flow_q25'] else 0)
    vol_signal = 1 if pd.notna(row['vol_adj']) and row['vol_adj'] < row['vol_q25'] else (-1 if pd.notna(row['vol_adj']) and row['vol_adj'] > row['vol_q75'] else 0)
    
    score = 0.4 * reg_signal + 0.2 * ma_signal + 0.2 * flow_signal + 0.2 * vol_signal
    
    if score >= 0.5:
        return pd.Series({'position': 1, 'signal_type': '强买', 'score': score})
    elif score >= 0.2:
        return pd.Series({'position': 1, 'signal_type': '买', 'score': score})
    elif score >= -0.2:
        return pd.Series({'position': 0, 'signal_type': '持', 'score': score})
    elif score >= -0.5:
        return pd.Series({'position': -1, 'signal_type': '卖', 'score': score})
    else:
        return pd.Series({'position': -1, 'signal_type': '强卖', 'score': score})

def strategy_C_reg10_only(row):
    """方案C: 纯reg10策略"""
    if pd.isna(row['reg10']):
        return pd.Series({'position': 0, 'signal_type': '持', 'score': 0})
    elif row['reg10'] < 0.03:
        return pd.Series({'position': 1, 'signal_type': '买', 'score': -1})
    elif row['reg10'] > 0.03:
        return pd.Series({'position': -1, 'signal_type': '卖', 'score': 1})
    else:
        return pd.Series({'position': 0, 'signal_type': '持', 'score': 0})

# 6. 应用三个策略
print("\n=== 5. 应用策略 ===")
print("计算方案A（独立三因子）...")
strategy_A = price_data.apply(strategy_A_only_factors, axis=1)
price_data['A_position'] = strategy_A['position']
price_data['A_signal_type'] = strategy_A['signal_type']
price_data['A_score'] = strategy_A['score']

print("计算方案B（融合策略）...")
strategy_B = price_data.apply(strategy_B_combined, axis=1)
price_data['B_position'] = strategy_B['position']
price_data['B_signal_type'] = strategy_B['signal_type']
price_data['B_score'] = strategy_B['score']

print("计算方案C（纯reg10）...")
strategy_C = price_data.apply(strategy_C_reg10_only, axis=1)
price_data['C_position'] = strategy_C['position']
price_data['C_signal_type'] = strategy_C['signal_type']
price_data['C_score'] = strategy_C['score']

# 7. 计算策略收益率
print("\n=== 6. 计算策略收益率 ===")
price_data['A_strategy_return'] = price_data['A_position'] * price_data['next_return']
price_data['B_strategy_return'] = price_data['B_position'] * price_data['next_return']
price_data['C_strategy_return'] = price_data['C_position'] * price_data['next_return']

# 8. 计算绩效指标
print("\n=== 7. 计算绩效指标 ===")

def calc_metrics(df, return_col):
    total_return = df[return_col].sum()
    total_days = len(df)
    annual_return = (1 + total_return) ** (252 / total_days) - 1 if total_days > 0 else 0
    sharpe_ratio = df[return_col].mean() / df[return_col].std() * np.sqrt(252) if df[return_col].std() > 0 else 0
    
    cumulative_return = (1 + df[return_col]).cumprod()
    peak = cumulative_return.expanding().max()
    drawdown = (cumulative_return - peak) / peak
    max_drawdown = drawdown.min()
    
    win_rate = (df[return_col] > 0).sum() / len(df) if len(df) > 0 else 0
    
    return {
        'total_return': total_return,
        'annual_return': annual_return,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'win_rate': win_rate,
    }

metrics_A = calc_metrics(price_data, 'A_strategy_return')
metrics_B = calc_metrics(price_data, 'B_strategy_return')
metrics_C = calc_metrics(price_data, 'C_strategy_return')

print("\n" + "=" * 60)
print("策略对比结果")
print("=" * 60)

print("\n【方案A: 独立三因子策略】")
print(f"  总收益率: {metrics_A['total_return']:.4f} ({metrics_A['total_return']*100:.2f}%)")
print(f"  年化收益率: {metrics_A['annual_return']:.4f} ({metrics_A['annual_return']*100:.2f}%)")
print(f"  夏普比率: {metrics_A['sharpe_ratio']:.4f}")
print(f"  最大回撤: {metrics_A['max_drawdown']:.4f} ({metrics_A['max_drawdown']*100:.2f}%)")
print(f"  胜率: {metrics_A['win_rate']:.4f} ({metrics_A['win_rate']*100:.2f}%)")

print("\n【方案B: 三因子+reg10融合策略】")
print(f"  总收益率: {metrics_B['total_return']:.4f} ({metrics_B['total_return']*100:.2f}%)")
print(f"  年化收益率: {metrics_B['annual_return']:.4f} ({metrics_B['annual_return']*100:.2f}%)")
print(f"  夏普比率: {metrics_B['sharpe_ratio']:.4f}")
print(f"  最大回撤: {metrics_B['max_drawdown']:.4f} ({metrics_B['max_drawdown']*100:.2f}%)")
print(f"  胜率: {metrics_B['win_rate']:.4f} ({metrics_B['win_rate']*100:.2f}%)")

print("\n【方案C: 纯reg10基准】")
print(f"  总收益率: {metrics_C['total_return']:.4f} ({metrics_C['total_return']*100:.2f}%)")
print(f"  年化收益率: {metrics_C['annual_return']:.4f} ({metrics_C['annual_return']*100:.2f}%)")
print(f"  夏普比率: {metrics_C['sharpe_ratio']:.4f}")
print(f"  最大回撤: {metrics_C['max_drawdown']:.4f} ({metrics_C['max_drawdown']*100:.2f}%)")
print(f"  胜率: {metrics_C['win_rate']:.4f} ({metrics_C['win_rate']*100:.2f}%)")

# 9. 信号分布对比
print("\n=== 8. 信号分布对比 ===")
print("\n方案A信号分布:")
print(price_data['A_signal_type'].value_counts())
print("\n方案B信号分布:")
print(price_data['B_signal_type'].value_counts())
print("\n方案C信号分布:")
print(price_data['C_signal_type'].value_counts())

# 10. 各信号收益率
print("\n=== 9. 各信号收益率 ===")
for prefix, name in [('A', '方案A'), ('B', '方案B'), ('C', '方案C')]:
    print(f"\n{name}各信号收益率:")
    signal_returns = price_data.groupby(f'{prefix}_signal_type')[f'{prefix}_strategy_return'].agg(['mean', 'std', 'count'])
    print(signal_returns)

# 11. 生成报告
print("\n=== 10. 生成报告 ===")
best_total = 'A' if metrics_A['total_return'] >= metrics_B['total_return'] and metrics_A['total_return'] >= metrics_C['total_return'] else ('B' if metrics_B['total_return'] >= metrics_C['total_return'] else 'C')
best_annual = 'A' if metrics_A['annual_return'] >= metrics_B['annual_return'] and metrics_A['annual_return'] >= metrics_C['annual_return'] else ('B' if metrics_B['annual_return'] >= metrics_C['annual_return'] else 'C')
best_sharpe = 'A' if metrics_A['sharpe_ratio'] >= metrics_B['sharpe_ratio'] and metrics_A['sharpe_ratio'] >= metrics_C['sharpe_ratio'] else ('B' if metrics_B['sharpe_ratio'] >= metrics_C['sharpe_ratio'] else 'C')
best_dd = 'A' if metrics_A['max_drawdown'] <= metrics_B['max_drawdown'] and metrics_A['max_drawdown'] <= metrics_C['max_drawdown'] else ('B' if metrics_B['max_drawdown'] <= metrics_C['max_drawdown'] else 'C')
best_wr = 'A' if metrics_A['win_rate'] >= metrics_B['win_rate'] and metrics_A['win_rate'] >= metrics_C['win_rate'] else ('B' if metrics_B['win_rate'] >= metrics_C['win_rate'] else 'C')

report = f"""
# 方案对比回测报告

## 1. 策略设计

### 方案A: 独立三因子策略
- 只用新因子（MA_decay, flow_alpha, vol_adj）
- 不使用reg10
- 逻辑：高MA_decay、高flow_alpha、低vol_adj → 看涨
- 交易规则：score>=2时持仓，score<=-1时清仓

### 方案B: 三因子+reg10融合策略
- 结合新因子和reg10
- 融合评分 = 0.4*reg_signal + 0.2*ma_signal + 0.2*flow_signal + 0.2*vol_signal
- 交易规则：score>=0.5时持仓，score<=-0.5时清仓

### 方案C: 纯reg10基准
- 只用reg10
- 逻辑：reg10<0.03看涨，reg10>0.03看跌
- 交易规则：reg10<0.03时持仓，reg10>0.03时清仓

## 2. 回测结果

### 数据概况
- 回测期间: {one_year_ago} ~ {today}
- 股票数量: {len(sample_stocks)}只
- 数据点: {len(price_data)}个

### 绩效指标对比

| 指标 | 方案A（独立三因子） | 方案B（融合策略） | 方案C（纯reg10） |
|------|-------------------|-----------------|----------------|
| 总收益率 | {metrics_A['total_return']:.4f} ({metrics_A['total_return']*100:.2f}%) | {metrics_B['total_return']:.4f} ({metrics_B['total_return']*100:.2f}%) | {metrics_C['total_return']:.4f} ({metrics_C['total_return']*100:.2f}%) |
| 年化收益率 | {metrics_A['annual_return']:.4f} ({metrics_A['annual_return']*100:.2f}%) | {metrics_B['annual_return']:.4f} ({metrics_B['annual_return']*100:.2f}%) | {metrics_C['annual_return']:.4f} ({metrics_C['annual_return']*100:.2f}%) |
| 夏普比率 | {metrics_A['sharpe_ratio']:.4f} | {metrics_B['sharpe_ratio']:.4f} | {metrics_C['sharpe_ratio']:.4f} |
| 最大回撤 | {metrics_A['max_drawdown']:.4f} ({metrics_A['max_drawdown']*100:.2f}%) | {metrics_B['max_drawdown']:.4f} ({metrics_B['max_drawdown']*100:.2f}%) | {metrics_C['max_drawdown']:.4f} ({metrics_C['max_drawdown']*100:.2f}%) |
| 胜率 | {metrics_A['win_rate']:.4f} ({metrics_A['win_rate']*100:.2f}%) | {metrics_B['win_rate']:.4f} ({metrics_B['win_rate']*100:.2f}%) | {metrics_C['win_rate']:.4f} ({metrics_C['win_rate']*100:.2f}%) |

## 3. 结论

### 最优策略
- **总收益率最高**: 方案{best_total}（{max(metrics_A['total_return'], metrics_B['total_return'], metrics_C['total_return'])*100:.2f}%）
- **年化收益率最高**: 方案{best_annual}（{max(metrics_A['annual_return'], metrics_B['annual_return'], metrics_C['annual_return'])*100:.2f}%）
- **夏普比率最高**: 方案{best_sharpe}（{max(metrics_A['sharpe_ratio'], metrics_B['sharpe_ratio'], metrics_C['sharpe_ratio']):.4f}）
- **最大回撤最小**: 方案{best_dd}（{min(metrics_A['max_drawdown'], metrics_B['max_drawdown'], metrics_C['max_drawdown'])*100:.2f}%）
- **胜率最高**: 方案{best_wr}（{max(metrics_A['win_rate'], metrics_B['win_rate'], metrics_C['win_rate'])*100:.2f}%）

### 综合评价
- 方案A（独立三因子）表现{'优秀' if metrics_A['total_return'] > metrics_C['total_return'] else '一般'}，年化收益率{'超过' if metrics_A['annual_return'] > 0.05 else '低于'}5%
- 方案B（融合策略）表现{'优秀' if metrics_B['total_return'] > metrics_C['total_return'] else '一般'}，年化收益率{'超过' if metrics_B['annual_return'] > 0.05 else '低于'}5%
- 方案C（纯reg10）作为基准，表现{'稳定' if abs(metrics_C['annual_return']) < 0.1 else '波动较大'}
- 方案B相比方案A，{'提升' if metrics_B['total_return'] > metrics_A['total_return'] else '略低'}{'{' + f'{metrics_B["total_return"] - metrics_A["total_return"]:.4f}' + '}' if metrics_B['total_return'] != metrics_A['total_return'] else ''}，说明reg10的加入{'有额外贡献' if metrics_B['total_return'] > metrics_A['total_return'] else '贡献有限'}
"""

# 保存报告
with open('reports/comparison_backtest_report.md', 'w') as f:
    f.write(report)

print("报告已保存到 reports/comparison_backtest_report.md")

# 关闭连接
conn.close()
print("\n回测完成！")
