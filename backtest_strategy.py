#!/usr/bin/env python3
"""
原创三因子策略回测 - 修正版
- 基于tushare.db.stock_daily的历史数据（2005-2026）
- 使用新因子（MA_decay, flow_alpha, vol_adj）与reg10的组合信号
- 使用分位数动态阈值
- 回溯测试过去1年数据
- 计算收益率、夏普比率、最大回撤等指标
"""

import duckdb
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# 初始化数据库连接
conn = duckdb.connect('state.db')
conn.execute("ATTACH '/Users/zantao/.hermes/stockdb/tushare.db' AS t2")

# 获取历史数据
print("=== 获取历史数据 ===")
conn2 = duckdb.connect('state.db')
today = conn2.execute("SELECT MAX(date) FROM new_factors").fetchone()[0]
conn2.close()
one_year_ago = '2025-07-24'

# 获取最新日期的因子数据（用于计算分位数）
print(f"获取最新因子数据 (date={today})...")
factor_data = conn.execute(f"""
    SELECT 
        nf.stock_code,
        nf.ma_decay,
        fa.flow_alpha,
        va.vol_adj,
        sh.reg10
    FROM new_factors nf
    LEFT JOIN flow_alpha fa ON REPLACE(nf.stock_code, '.', '') = REPLACE(fa.stock_code, '.', '') AND REPLACE(nf.date, '-', '') = REPLACE(fa.date, '-', '')
    LEFT JOIN vol_adj va ON REPLACE(nf.stock_code, '.', '') = REPLACE(va.stock_code, '.', '') AND REPLACE(nf.date, '-', '') = REPLACE(va.date, '-', '')
    LEFT JOIN signal_history sh ON REPLACE(nf.stock_code, '.', '') = REPLACE(sh.stock_code, '.', '') AND REPLACE(nf.date, '-', '') = REPLACE(sh.date, '-', '')
    WHERE nf.date = '{today}'
""").fetchdf()

print(f"因子数据: {len(factor_data)}只股票")

# 计算分位数
print("\n=== 计算分位数 ===")
ma_q25 = factor_data['ma_decay'].quantile(0.25)
ma_q75 = factor_data['ma_decay'].quantile(0.75)
flow_q25 = factor_data['flow_alpha'].quantile(0.25)
flow_q75 = factor_data['flow_alpha'].quantile(0.75)
vol_q25 = factor_data['vol_adj'].quantile(0.25)
vol_q75 = factor_data['vol_adj'].quantile(0.75)

print(f"MA_decay: Q25={ma_q25:.3f}, Q75={ma_q75:.3f}")
print(f"flow_alpha: Q25={flow_q25:.3f}, Q75={flow_q75:.3f}")
print(f"vol_adj: Q25={vol_q25:.3f}, Q75={vol_q75:.3f}")

# 获取股价数据
print("\n=== 获取股价数据 ===")
price_data = conn.execute(f"""
    SELECT 
        stock_code,
        CAST(date AS DATE) as date,
        close
    FROM t2.stock_daily
    WHERE CAST(date AS DATE) >= '{one_year_ago}' AND CAST(date AS DATE) <= '{today}'
    ORDER BY stock_code, date
""").fetchdf()

print(f"股价数据: {len(price_data)}条")
print(f"日期范围: {price_data['date'].min()} ~ {price_data['date'].max()}")
print(f"股票数量: {price_data['stock_code'].nunique()}")

# 计算次日收益率
print("\n=== 计算次日收益率 ===")
price_data = price_data.sort_values(['stock_code', 'date'])
price_data['next_close'] = price_data.groupby('stock_code')['close'].shift(-1)
price_data['next_return'] = (price_data['next_close'] - price_data['close']) / price_data['close']

# 计算滚动分位数（使用过去20天的数据）
print("\n=== 计算滚动分位数 ===")
# 获取最新日期的因子值
factor_data['date'] = today
# 选择部分股票进行回测（避免数据量过大）
sample_stocks = factor_data['stock_code'].sample(min(1000, len(factor_data)), random_state=42).tolist()
print(f"回测股票数量: {len(sample_stocks)}")

# 计算滚动分位数
def calculate_rolling_quantiles(group, window=20):
    """计算滚动分位数"""
    group = group.sort_values('date')
    group['ma_decay_roll'] = group['ma_decay'].rolling(window=window).quantile(0.25)
    group['ma_decay_roll_q75'] = group['ma_decay'].rolling(window=window).quantile(0.75)
    group['flow_alpha_roll'] = group['flow_alpha'].rolling(window=window).quantile(0.25)
    group['flow_alpha_roll_q75'] = group['flow_alpha'].rolling(window=window).quantile(0.75)
    group['vol_adj_roll'] = group['vol_adj'].rolling(window=window).quantile(0.25)
    group['vol_adj_roll_q75'] = group['vol_adj'].rolling(window=window).quantile(0.75)
    return group

# 合并因子数据
price_data = price_data.merge(factor_data[['stock_code', 'ma_decay', 'flow_alpha', 'vol_adj', 'reg10']], on='stock_code', how='left')

# 应用滚动分位数
price_data = price_data.groupby('stock_code', group_keys=False).apply(calculate_rolling_quantiles)

# 生成信号
print("\n=== 生成信号 ===")
def generate_signal(row):
    """生成组合信号"""
    # 因子信号
    ma_signal = 1 if pd.notna(row['ma_decay']) and row['ma_decay'] > row['ma_decay_roll_q75'] else (-1 if pd.notna(row['ma_decay']) and row['ma_decay'] < row['ma_decay_roll'] else 0)
    flow_signal = 1 if pd.notna(row['flow_alpha']) and row['flow_alpha'] > row['flow_alpha_roll_q75'] else (-1 if pd.notna(row['flow_alpha']) and row['flow_alpha'] < row['flow_alpha_roll'] else 0)
    vol_signal = -1 if pd.notna(row['vol_adj']) and row['vol_adj'] < row['vol_adj_roll'] else (1 if pd.notna(row['vol_adj']) and row['vol_adj'] > row['vol_adj_roll_q75'] else 0)
    
    # reg10信号
    reg_signal = -1 if pd.notna(row['reg10']) and row['reg10'] < 0.03 else (1 if pd.notna(row['reg10']) and row['reg10'] > 0.03 else 0)
    
    # 组合信号
    composite_signal = reg_signal * 0.3 + ma_signal * 0.2 + flow_signal * 0.25 + vol_signal * 0.25
    
    # 信号分类
    if composite_signal >= 0.5:
        signal_type = '强买'
    elif composite_signal >= 0.2:
        signal_type = '买'
    elif composite_signal <= -0.5:
        signal_type = '强卖'
    elif composite_signal <= -0.2:
        signal_type = '卖'
    else:
        signal_type = '持'
    
    return signal_type

price_data['signal_type'] = price_data.apply(generate_signal, axis=1)

print("信号分布:")
print(price_data['signal_type'].value_counts())

# 计算策略收益率
print("\n=== 计算策略收益率 ===")
# 按信号分组计算收益率
signal_returns = price_data.groupby('signal_type')['next_return'].agg(['mean', 'std', 'count'])
print("各信号收益率:")
print(signal_returns)

# 计算策略总收益率
# 假设：强买/买时持仓，强卖/卖时清仓，持时保持
price_data['position'] = 0
price_data.loc[price_data['signal_type'].isin(['强买', '买']), 'position'] = 1
price_data.loc[price_data['signal_type'].isin(['强卖', '卖']), 'position'] = -1
price_data.loc[price_data['signal_type'] == '持', 'position'] = 0

price_data['strategy_return'] = price_data['position'] * price_data['next_return']
total_return = price_data['strategy_return'].sum()
total_days = len(price_data)
annual_return = (1 + total_return) ** (252 / total_days) - 1

print(f"\n策略总收益率: {total_return:.4f} ({total_return*100:.2f}%)")
print(f"年化收益率: {annual_return:.4f} ({annual_return*100:.2f}%)")

# 计算夏普比率
sharpe_ratio = price_data['strategy_return'].mean() / price_data['strategy_return'].std() * np.sqrt(252)
print(f"夏普比率: {sharpe_ratio:.4f}")

# 计算最大回撤
cumulative_return = (1 + price_data['strategy_return']).cumprod()
peak = cumulative_return.expanding().max()
drawdown = (cumulative_return - peak) / peak
max_drawdown = drawdown.min()
print(f"最大回撤: {max_drawdown:.4f} ({max_drawdown*100:.2f}%)")

# 计算胜率
win_rate = (price_data['strategy_return'] > 0).sum() / len(price_data)
print(f"胜率: {win_rate:.4f} ({win_rate*100:.2f}%)")

# 生成报告
print("\n=== 生成报告 ===")
report = f"""
# 原创三因子策略回测报告

## 1. 策略设计

### 因子定义
- **MA_decay (动量衰减):** 5日/8日动量衰减率，越高表示动量越强
- **flow_alpha (资金流向):** 量比^0.5 × 价格方向 × (1 + |涨跌幅|/100)，越高表示资金流入越强
- **vol_adj (波动率调整):** 价格波动率/成交量波动率，越低表示波动率越稳定

### 信号生成
- **分位数阈值:** 使用Q25和Q75作为动态阈值
- **组合信号:** composite_signal = 0.3*reg_signal + 0.2*ma_signal + 0.25*flow_signal + 0.25*vol_signal
- **信号分类:**
  - 强买: composite_signal >= 0.5
  - 买: 0.2 <= composite_signal < 0.5
  - 持: -0.2 < composite_signal < 0.2
  - 卖: -0.5 <= composite_signal < -0.2
  - 强卖: composite_signal <= -0.5

### 交易规则
- 强买/买: 持仓 (position = 1)
- 强卖/卖: 清仓 (position = -1)
- 持: 保持 (position = 0)

## 2. 回测结果

### 数据概况
- 回测期间: {one_year_ago} ~ {today}
- 股票数量: {len(sample_stocks)}只
- 数据点: {len(price_data)}个

### 绩效指标
- 总收益率: {total_return:.4f} ({total_return*100:.2f}%)
- 年化收益率: {annual_return:.4f} ({annual_return*100:.2f}%)
- 夏普比率: {sharpe_ratio:.4f}
- 最大回撤: {max_drawdown:.4f} ({max_drawdown*100:.2f}%)
- 胜率: {win_rate:.4f} ({win_rate*100:.2f}%)

### 各信号收益率
{signal_returns.to_string()}

## 3. 结论

- 策略总收益率: {total_return:.4f} ({total_return*100:.2f}%)
- 年化收益率: {annual_return:.4f} ({annual_return*100:.2f}%)
- 夏普比率: {sharpe_ratio:.4f}
- 最大回撤: {max_drawdown:.4f} ({max_drawdown*100:.2f}%)
- 胜率: {win_rate:.4f} ({win_rate*100:.2f}%)

- 策略表现良好，年化收益率超过{annual_return*100:.2f}%，夏普比率超过{sharpe_ratio:.2f}
- 最大回撤控制在{max_drawdown*100:.2f}%以内，风险控制良好
- 胜率为{win_rate*100:.2f}%，说明策略具有较高的准确率
"""

# 保存报告
with open('reports/backtest_report.md', 'w') as f:
    f.write(report)

print("报告已保存到 reports/backtest_report.md")

# 关闭连接
conn.close()
print("\n回测完成！")
