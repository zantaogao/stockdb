import pandas as pd
import numpy as np

def calculate_trifactor_cmmr_fusion(df):
    """
    CMMR + 深度融合策略（修正版）
    注意：文件名 trifactor 与注释里的"三因子"是历史误称（2026-08-02 发现、2026-08-10 更正）——
    实际 old_score 是 v8 三模型融合分（reg10/20/40 LGBM 预测）的百分位，不是三因子（ma/flow/vol）融合分。
    "融合"的是模型预测，趋势系数仅做放大/打折。
    去掉 reg10 超卖加分（reg10 是模型预测，不是真实涨跌幅），只保留趋势系数
    
    核心逻辑：
    fusion_score = old_score × trend_multiplier
    
    趋势系数由 MA40 斜率决定，趋势向上放大，趋势向下打折。
    
    输入: df (必须包含 'old_score', 'ma40_slope')
    输出: df (新增 'fusion_score' 列，范围 0+)
    """
    df = df.copy()
    
    # --- 1. 数据准备 ---
    required_cols = ['old_score', 'ma40_slope']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # --- 2. CMMR 趋势安全系数 (乘数) ---
    # 逻辑：
    #   slope > 0.05 (强趋势向上) -> 1.3x
    #   0 < slope <= 0.05 (温和向上) -> 1.0x
    #   -0.02 < slope <= 0 (弱向下) -> 0.8x
    #   slope <= -0.02 (强向下) -> 0.5x
    df['trend_multiplier'] = 1.0
    df.loc[df['ma40_slope'] > 0.05, 'trend_multiplier'] = 1.3
    df.loc[(df['ma40_slope'] > -0.02) & (df['ma40_slope'] <= 0), 'trend_multiplier'] = 0.8
    df.loc[df['ma40_slope'] <= -0.02, 'trend_multiplier'] = 0.5
    
    # --- 3. 融合分计算 ---
    df['fusion_score'] = df['old_score'] * df['trend_multiplier']
    
    return df
