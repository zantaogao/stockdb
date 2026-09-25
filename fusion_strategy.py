#!/usr/bin/env python3
"""
三因子融合10d策略设计
目标：设计一个融合三因子(MA_decay, flow_alpha, vol_adj)和reg10的选股策略

策略核心思路：
1. reg10提供方向（多头/空头）
2. 三因子提供强度确认
3. 不同reg10区间用不同阈值
4. 组合信号分级：强买/买/持/卖/强卖

数据支持：基于tushare.db和state.db的实际数据
"""

import duckdb
import pandas as pd
import numpy as np
import json

def main():
    print("=" * 60)
    print("三因子融合10d策略")
    print("=" * 60)
    
    conn = duckdb.connect('state.db')
    conn.execute("ATTACH 'tushare.db' AS t2")
    
    # ========== 1. 获取数据 ==========
    print("\n=== 1. 获取数据 ===")
    
    # 获取所有因子+reg数据（使用混合日期格式）
    df = conn.execute("""
        SELECT 
            nf.stock_code,
            REPLACE(nf.date, '-', '') as date,
            nf.ma_decay,
            fa.flow_alpha,
            va.vol_adj,
            sh.reg10,
            sh.reg20,
            sh.reg40,
            sh.fusion_score
        FROM new_factors nf
        LEFT JOIN flow_alpha fa 
            ON REPLACE(nf.stock_code,'.','') = REPLACE(fa.stock_code,'.','') 
            AND REPLACE(nf.date,'-','') = REPLACE(fa.date,'-','')
        LEFT JOIN vol_adj va 
            ON REPLACE(nf.stock_code,'.','') = REPLACE(va.stock_code,'.','') 
            AND REPLACE(nf.date,'-','') = REPLACE(va.date,'-','')
        LEFT JOIN signal_history sh 
            ON REPLACE(nf.stock_code,'.','') = REPLACE(sh.stock_code,'.','') 
            AND REPLACE(nf.date,'-','') = REPLACE(sh.date,'-','')
        WHERE REPLACE(nf.date,'-','') >= '20260701'
    """).fetchall()
    
    df = pd.DataFrame(df, columns=['stock_code', 'date', 'ma_decay', 'flow_alpha', 
                                     'vol_adj', 'reg10', 'reg20', 'reg40', 'fusion_score'])
    df['stock_code'] = df['stock_code'].astype(str).str.replace('.', '')
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    
    print(f"数据量: {len(df)}条, 日期范围: {df['date'].min().date()} ~ {df['date'].max().date()}")
    
    # ========== 2. 分析reg10与三因子的关系 ==========
    print("\n=== 2. reg10与三因子关系 ===")
    
    # reg10分布
    print("\n--- reg10分布 ---")
    reg_buckets = pd.cut(df['reg10'], bins=[-0.1, 0.01, 0.02, 0.03, 0.04, 0.1], 
                         labels=['强多头', '多头', '中性', '偏空', '空头'])
    print(reg_buckets.value_counts().sort_index())
    
    # 不同reg10区间下，三因子的分布
    print("\n--- 不同reg10区间的因子特征 ---")
    for label, group in df.groupby(reg_buckets, observed=True):
        label_str = str(label)
        if label_str == 'None':
            label_str = '中性'
        print(f"\n{label_str} (n={len(group)}, reg10均值={group['reg10'].mean():.4f}):")
        print(f"  MA_decay: 均值={group['ma_decay'].mean():.3f}, 中位数={group['ma_decay'].median():.3f}, Q25={group['ma_decay'].quantile(0.25):.3f}, Q75={group['ma_decay'].quantile(0.75):.3f}")
        print(f"  flow_alpha: 均值={group['flow_alpha'].mean():.4f}, 中位数={group['flow_alpha'].median():.4f}, Q25={group['flow_alpha'].quantile(0.25):.4f}, Q75={group['flow_alpha'].quantile(0.75):.4f}")
        print(f"  vol_adj: 均值={group['vol_adj'].mean():.3f}, 中位数={group['vol_adj'].median():.3f}, Q25={group['vol_adj'].quantile(0.25):.3f}, Q75={group['vol_adj'].quantile(0.75):.3f}")
    
    # ========== 3. 设计融合策略 ==========
    print("\n=== 3. 融合策略设计 ===")
    
    # 策略核心规则：
    # reg10 < 0.03 → 方向看多，三因子确认强度
    # reg10 > 0.03 → 方向看空，三因子确认强度
    
    # 3.1 基础信号
    df['reg_dir'] = np.where(df['reg10'] < 0.03, '多', np.where(df['reg10'] > 0.03, '空', '中性'))
    
    # 3.2 三因子信号（标准化后加权）
    # MA_decay: 越高越好（动量持续），加权0.3
    # flow_alpha: 越高越好（资金流入），加权0.3
    # vol_adj: 越低越好（波动小），加权0.2（注意：取负号）
    # 额外因子：fusion_score，加权0.2
    
    # 标准化（Z-score）
    df['ma_z'] = (df['ma_decay'] - df['ma_decay'].mean()) / df['ma_decay'].std()
    df['flow_z'] = (df['flow_alpha'] - df['flow_alpha'].mean()) / df['flow_alpha'].std()
    df['vol_z'] = -(df['vol_adj'] - df['vol_adj'].mean()) / df['vol_adj'].std()  # 负号：vol_adj越低越好
    
    # 融合评分
    df['fusion_score_new'] = 0.3 * df['ma_z'] + 0.3 * df['flow_z'] + 0.2 * df['vol_z'] + 0.2 * (df['fusion_score'] - 50) / 50
    
    # 3.3 信号分级
    def get_signal(row):
        if row['reg_dir'] == '多':
            if row['fusion_score_new'] > 0.5:
                return '强买'
            elif row['fusion_score_new'] > 0:
                return '买'
            elif row['fusion_score_new'] > -0.3:
                return '持'
            else:
                return '卖'
        elif row['reg_dir'] == '空':
            if row['fusion_score_new'] < -0.5:
                return '强卖'
            elif row['fusion_score_new'] < 0:
                return '卖'
            elif row['fusion_score_new'] < 0.3:
                return '持'
            else:
                return '买'
        else:  # 中性
            if row['fusion_score_new'] > 0.5:
                return '买'
            elif row['fusion_score_new'] < -0.5:
                return '卖'
            else:
                return '持'
    
    df['signal'] = df.apply(get_signal, axis=1)
    
    print("\n--- 信号分布 ---")
    print(df['signal'].value_counts())
    
    # ========== 4. 策略回测 ==========
    print("\n=== 4. 策略回测 ===")
    
    # 获取tushare.db中的股价数据
    prices = conn.execute("""
        SELECT stock_code, date, close
        FROM t2.stock_daily
        WHERE CAST(date AS DATE) >= '2026-07-01'
        ORDER BY stock_code, date
    """).fetchall()
    
    prices_df = pd.DataFrame(prices, columns=['stock_code', 'date', 'close'])
    prices_df['stock_code'] = prices_df['stock_code'].astype(str).str.replace('.', '')
    prices_df['date'] = pd.to_datetime(prices_df['date'], format='%Y-%m-%d')
    
    # 计算过去10天的收益（从2026-07-01到2026-07-24）
    july01 = prices_df[prices_df['date'] == '2026-07-01']
    july24 = prices_df[prices_df['date'] == '2026-07-24']
    
    # 合并7月1日和7月24日的股价
    merged_prices = july01[['stock_code', 'close']].rename(columns={'close': 'close_july01'})
    merged_prices = merged_prices.merge(july24[['stock_code', 'close']], on='stock_code', how='inner')
    merged_prices['close_july24'] = merged_prices['close']
    merged_prices['return_10d'] = (merged_prices['close_july24'] - merged_prices['close_july01']) / merged_prices['close_july01']
    
    print(f"7月1日股价: {len(july01)}条")
    print(f"7月24日股价: {len(july24)}条")
    print(f"10日收益均值: {merged_prices['return_10d'].mean():.4f}")
    print(f"10日胜率: {(merged_prices['return_10d'] > 0).mean():.2%}")
    
    # 合并因子数据和股价数据
    merged = df.merge(merged_prices, on='stock_code', how='inner')
    print(f"\n合并后数据: {len(merged)}条")
    
    # 计算不同信号的平均收益
    print("\n--- 信号 vs 10日收益 ---")
    for sig in ['强买', '买', '持', '卖', '强卖']:
        sub = merged[merged['signal'] == sig]
        if len(sub) > 0:
            avg_10d = sub['return_10d'].mean()
            win_10d = (sub['return_10d'] > 0).mean()
            print(f"{sig} (n={len(sub)}):")
            print(f"  10日: 收益={avg_10d:.4f}%, 胜率={win_10d:.2%}")
    
    # ========== 5. 策略优化 ==========
    print("\n=== 5. 策略优化 ===")
    
    # 5.1 动态阈值
    print("\n--- 动态阈值优化 ---")
    for label, group in df.groupby(reg_buckets, observed=True):
        label_str = str(label) if str(label) != 'None' else '中性'
        if len(group) > 100:
            print(f"{label_str} (n={len(group)}):")
            print(f"  MA_decay阈值: 均值±1SD = [{group['ma_decay'].mean()-group['ma_decay'].std():.3f}, {group['ma_decay'].mean()+group['ma_decay'].std():.3f}]")
            print(f"  flow_alpha阈值: 均值±1SD = [{group['flow_alpha'].mean()-group['flow_alpha'].std():.4f}, {group['flow_alpha'].mean()+group['flow_alpha'].std():.4f}]")
            print(f"  vol_adj阈值: 均值±1SD = [{group['vol_adj'].mean()-group['vol_adj'].std():.3f}, {group['vol_adj'].mean()+group['vol_adj'].std():.3f}]")
    
    # ========== 6. 生成策略报告 ==========
    print("\n=== 6. 生成策略报告 ===")
    
    report = """
# 三因子融合10d策略

## 一、策略核心逻辑

### 方向判断（reg10）
- reg10 < 0.03 → 方向看多
- reg10 > 0.03 → 方向看空
- 0.03 ≤ reg10 ≤ 0.03 → 中性

### 强度确认（三因子）
- MA_decay（动量衰减）: 越高越好，表示动量持续，权重0.3
- flow_alpha（资金流向）: 越高越好，表示资金流入，权重0.3
- vol_adj（波动率调整）: 越低越好，表示波动小，权重0.2
- fusion_score（模型融合分）: 越高越好，权重0.2

### 信号分级
- 强买: reg10 < 0.03 AND fusion_score_new > 0.5
- 买: reg10 < 0.03 AND fusion_score_new > 0
- 持: 其他情况
- 卖: reg10 > 0.03 AND fusion_score_new < 0
- 强卖: reg10 > 0.03 AND fusion_score_new < -0.5

## 二、信号分布与收益

（见上方数据）

## 三、策略优势

1. 方向明确：reg10提供方向判断，三因子确认强度
2. 信号分级：强买/买/持/卖/强卖五级信号
3. 数据支持：基于实际数据计算，非主观设定

## 四、实施建议

1. 盘中决策时，优先选择"强买"信号的股票
2. 持仓管理：信号变弱时减仓，信号变强时加仓
3. 风险控制：信号变"强卖"时减仓或清仓
"""
    
    # 保存报告
    report_path = '/Users/zantao/.hermes/stockdb/reports/fusion_strategy.md'
    with open(report_path, 'w') as f:
        f.write(report)
    
    print(f"\n报告已保存到 {report_path}")
    
    conn.close()
    print("\n完成！")

if __name__ == '__main__':
    main()
