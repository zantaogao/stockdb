import pandas as pd
import numpy as np

def calculate_cmmr_score(df):
    """
    CMMR 独立策略：周期错位 + 均值回归（纯防守型）
    完全独立计算，不依赖任何原有评分
    
    输入: df (包含 pct_chg_10d, ma40, close, open, vol_ratio 等列)
    输出: df (新增 'cmmr_score' 列，范围 0-100)
    """
    df = df.copy()
    
    # --- 1. 数据准备 ---
    required_cols = ['pct_chg_10d', 'ma40', 'close', 'open']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # 计算 MA40 斜率（20 天变化率）
    if 'ma40_lag20' not in df.columns:
        df['ma40_lag20'] = df['ma40'].shift(20)
    
    df['ma40_slope'] = (df['ma40'] - df['ma40_lag20']) / df['ma40_lag20'].replace(0, np.nan)
    
    # --- 2. CMMR 核心因子 ---
    
    # F1: 趋势分 (0-40 分)
    # 逻辑：
    #   slope > 0.02 (强趋势向上) -> 40 分
    #   0 < slope <= 0.02 (温和向上) -> 20 分
    #   slope <= 0 (趋势向下或持平) -> 0 分
    df['cmmr_trend'] = 0.0
    df.loc[df['ma40_slope'] > 0.02, 'cmmr_trend'] = 40.0
    df.loc[(df['ma40_slope'] > 0) & (df['ma40_slope'] <= 0.02), 'cmmr_trend'] = 20.0
    
    # F2: 超卖分 (0-40 分)
    # 使用真实 10 日涨跌幅 (pct_chg_10d)，非模型预测
    # 逻辑：
    #   过去 10 日跌幅 > 8% (极端超卖) -> 40 分
    #   过去 10 日跌幅 4%-8% (中度超卖) -> 20 分
    #   其他 -> 0 分
    df['cmmr_oversold'] = 0.0
    df.loc[df['pct_chg_10d'] < -0.08, 'cmmr_oversold'] = 40.0
    df.loc[(df['pct_chg_10d'] >= -0.08) & (df['pct_chg_10d'] < -0.04), 'cmmr_oversold'] = 20.0
    
    # F3: 量能分 (0-20 分)
    if 'vol_ratio' not in df.columns:
        df['vol_ratio'] = 1.0
    
    df['cmmr_vol'] = 0.0
    df.loc[(df['vol_ratio'] < 0.8) | ((df['vol_ratio'] > 1.2) & (df['close'] > df['open'])), 'cmmr_vol'] = 20.0
    
    # --- 3. 总分计算 ---
    df['cmmr_score'] = df['cmmr_trend'] + df['cmmr_oversold'] + df['cmmr_vol']
    
    # 安全红线：趋势向下 (slope < 0) 直接给 0 分（避免接飞刀）
    df.loc[df['ma40_slope'] < 0, 'cmmr_score'] = 0.0
    
    return df
