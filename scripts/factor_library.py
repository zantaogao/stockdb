#!/usr/bin/env python3
"""
因子库 v1 — 因子注册表 + 统一计算 + IC追踪 + 自动生成特征矩阵

用法:
  python3 factor_library.py init       # 初始化因子注册表
  python3 factor_library.py compute    # 计算所有因子并存入DB
  python3 factor_library.py ic         # 更新各因子IC
  python3 factor_library.py features   # 生成LightGBM特征矩阵
  python3 factor_library.py status     # 查看因子全景
"""

import os, sys, json, math
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

HOME = os.path.expanduser('~')
# DB 已废弃，现在统一用 TUSHARE_DB_PATH
from core.db import TUSHARE_DB_PATH, get_tushare_db

# ============================================================
# 因子定义 — 所有因子在这里注册
# ============================================================
# 格式: name -> {calc, source, horizon, weight_category, description}
FACTOR_DEFS = {
    # --- 动量因子 ---
    'mom_5': {
        'calc': 'close / lag(close, 5) - 1',
        'source': 'daily',
        'horizon': 'short',
        'group': 'momentum',
        'desc': '5日涨幅',
        'active': True,
    },
    'mom_10': {
        'calc': 'close / lag(close, 10) - 1',
        'source': 'daily',
        'horizon': 'short',
        'group': 'momentum',
        'desc': '10日涨幅',
        'active': True,
    },
    'mom_20': {
        'calc': 'close / lag(close, 20) - 1',
        'source': 'daily',
        'horizon': 'medium',
        'group': 'momentum',
        'desc': '20日涨幅',
        'active': True,
    },
    'mom_60': {
        'calc': 'close / lag(close, 60) - 1',
        'source': 'daily',
        'horizon': 'long',
        'group': 'momentum',
        'desc': '60日涨幅',
        'active': True,
    },
    # --- 波动率因子 ---
    'vol_20': {
        'calc': 'std(ret, 20) * sqrt(252)',
        'source': 'daily',
        'horizon': 'short',
        'group': 'volatility',
        'desc': '20日波动率(年化)',
        'active': True,
    },
    'vol_60': {
        'calc': 'std(ret, 60) * sqrt(252)',
        'source': 'daily',
        'horizon': 'medium',
        'group': 'volatility',
        'desc': '60日波动率(年化)',
        'active': True,
    },
    # --- 换手率因子 ---
    'turn_5': {
        'calc': 'avg(turn_rate, 5)',
        'source': 'daily',
        'horizon': 'short',
        'group': 'liquidity',
        'desc': '5日平均换手率',
        'active': True,
    },
    'turn_20': {
        'calc': 'avg(turn_rate, 20)',
        'source': 'daily',
        'horizon': 'medium',
        'group': 'liquidity',
        'desc': '20日平均换手率',
        'active': True,
    },
    # --- 估值因子 ---
    'ep_ttm': {
        'calc': '1 / pe_ttm',
        'source': 'stock_valuation',
        'horizon': 'static',
        'group': 'valuation',
        'desc': '市盈率倒数(E/P)',
        'active': True,
    },
    'bp': {
        'calc': '1 / pb',
        'source': 'stock_valuation',
        'horizon': 'static',
        'group': 'valuation',
        'desc': '市净率倒数(B/P)',
        'active': True,
    },
    # --- 市值因子 ---
    'ln_cap': {
        'calc': 'log(total_mv)',
        'source': 'stock_valuation',
        'horizon': 'static',
        'group': 'size',
        'desc': '对数总市值',
        'active': True,
    },
    # --- 质量因子 ---
    'roe': {
        'calc': 'roe(最新财报)',
        'source': 'fin_income',
        'horizon': 'static',
        'group': 'quality',
        'desc': '净资产收益率',
        'active': True,
    },
    # --- 资金流因子（暂未启用，等数据积累）---
    'mf_net': {
        'calc': 'main_net / 1e8',
        'source': 'money_flow',
        'horizon': 'short',
        'group': 'money_flow',
        'desc': '主力净流入(亿元)',
        'active': False,  # 数据不足，暂不启用
    },
    # --- GTJA 191 Alpha因子（Vibe-Trading计算，A股有效）---
    'gtja_042': {
        'calc': '(-1*RANK(STD(HIGH,10)))*CORR(HIGH,VOLUME,10)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#42: 高价波动率×量价相关(IC=+0.080)',
        'active': False,  # 待启用——需要vibe_trading桥
    },
    'gtja_070_inv': {
        'calc': '-1*(RANK(MAX(VWAP-CLOSE,3))+RANK(MIN(VWAP-CLOSE,3)))*RANK(DELTA(VOLUME,3))',
        'source': 'vibe_trading',
        'horizon': 'short',
        'group': 'gtja',
        'desc': 'GTJA#70取反: VWAP偏离+量变(IC=+0.086)',
        'active': False,
    },
    # --- GTJA Alpha因子（Vibe-Trading计算，A股有效）---
    'gtja_alpha_150_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.084,夏普=-8.7)',
        'active': False,
    },
    'gtja_alpha_158_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.070,夏普=-6.6)',
        'active': False,
    },
    'gtja_alpha_159_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.066,夏普=-5.3)',
        'active': False,
    },
    'gtja_alpha_167_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.060,夏普=-5.1)',
        'active': False,
    },
    'gtja_alpha_175_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.053,夏普=-4.4)',
        'active': False,
    },
    'gtja_alpha_187_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.051,夏普=-4.4)',
        'active': False,
    },
    'gtja_alpha_184': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.051,夏普=7.5)',
        'active': False,
    },
    'gtja_alpha_168': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.050,夏普=8.1)',
        'active': False,
    },
    'gtja_alpha_189_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.049,夏普=-4.1)',
        'active': False,
    },
    'gtja_alpha_147_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.049,夏普=-5.5)',
        'active': False,
    },
    'gtja_alpha_151_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.049,夏普=-5.0)',
        'active': False,
    },
    'gtja_alpha_145_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.048,夏普=-8.1)',
        'active': False,
    },
    'gtja_alpha_161_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.047,夏普=-3.9)',
        'active': False,
    },
    'gtja_alpha_177': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.047,夏普=7.0)',
        'active': False,
    },
    'gtja_alpha_157': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.046,夏普=5.7)',
        'active': False,
    },
    'gtja_alpha_144': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.041,夏普=4.1)',
        'active': False,
    },
    'gtja_alpha_156': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.041,夏普=5.5)',
        'active': False,
    },
    'gtja_alpha_185': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.040,夏普=5.0)',
        'active': False,
    },
    'gtja_alpha_179_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.040,夏普=-10.2)',
        'active': False,
    },
    'gtja_alpha_140': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.039,夏普=5.9)',
        'active': False,
    },
    'gtja_alpha_176_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.037,夏普=-10.8)',
        'active': False,
    },
    'gtja_alpha_164': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.035,夏普=3.1)',
        'active': False,
    },
    'gtja_alpha_182': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.034,夏普=3.8)',
        'active': False,
    },
    'gtja_alpha_149': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.033,夏普=2.6)',
        'active': False,
    },
    'gtja_alpha_190': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.033,夏普=6.3)',
        'active': False,
    },
    'gtja_alpha_155_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.031,夏普=-5.5)',
        'active': False,
    },
    'gtja_alpha_173_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.030,夏普=-2.7)',
        'active': False,
    },
    'gtja_alpha_174_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.029,夏普=-2.4)',
        'active': False,
    },
    'gtja_alpha_169_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.029,夏普=-3.2)',
        'active': False,
    },
    'gtja_alpha_143_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.028,夏普=-2.3)',
        'active': False,
    },
    'gtja_alpha_165': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.026,夏普=4.4)',
        'active': False,
    },
    'gtja_alpha_162_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.026,夏普=-3.3)',
        'active': False,
    },
    'gtja_alpha_148': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.025,夏普=4.5)',
        'active': False,
    },
    'gtja_alpha_188_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.024,夏普=-4.0)',
        'active': False,
    },
    'gtja_alpha_183': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.023,夏普=4.0)',
        'active': False,
    },
    'gtja_alpha_160_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.023,夏普=-1.9)',
        'active': False,
    },
    'gtja_alpha_166': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha(IC=+0.022,夏普=3.2)',
        'active': False,
    },
    'gtja_alpha_153_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.021,夏普=-1.9)',
        'active': False,
    },
    'gtja_alpha_152_inv': {
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#alpha取反(IC=+0.020,夏普=-2.2)',
        'active': False,
    },
    'gtja_150_inv': {
        'calc': '-1*(CLOSE+HIGH)/2',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#150取反: 均价(IC=+0.084)',
        'active': False,
    },
    'gtja_095_inv': {
        'calc': '-1*RANK((OPEN-DELAY(CLOSE,1)))',
        'source': 'vibe_trading',
        'horizon': 'short',
        'group': 'gtja',
        'desc': 'GTJA#95取反: 开盘跳空(IC=+0.079)',
        'active': False,
    },
    'gtja_055_inv': {
        'calc': '-1*(CLOSE-DELAY(CLOSE,5))/DELAY(CLOSE,5)*100',
        'source': 'vibe_trading',
        'horizon': 'short',
        'group': 'gtja',
        'desc': 'GTJA#55取反: 5日涨幅(IC=+0.078)',
        'active': False,
    },
    'gtja_083': {
        'calc': '量价背离公式（复杂）',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#83: 量价背离(IC=+0.061,夏普14.3)',
        'active': False,
    },
    'gtja_099': {
        'calc': '波动率反转公式（复杂）',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#99: 波动率反转(IC=+0.061,夏普14.1)',
        'active': False,
    },
    'gtja_046': {
        'calc': '(MEDIAN(CLOSE,5)-CLOSE)+...',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#46: 中位数偏离(IC=+0.065)',
        'active': False,
    },
    'gtja_041': {
        'calc': '高低价差类',
        'source': 'vibe_trading',
        'horizon': 'short',
        'group': 'gtja',
        'desc': 'GTJA#41: 高低价差(IC=+0.058)',
        'active': False,
    },
    'gtja_062': {
        'calc': 'VWAP偏离类',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#62: VWAP偏离(IC=+0.056,夏普13.0)',
        'active': False,
    },
    'gtja_184': {
        'calc': '尾盘动量类',
        'source': 'vibe_trading',
        'horizon': 'short',
        'group': 'gtja',
        'desc': 'GTJA#184: 尾盘动量(IC=+0.051)',
        'active': False,
    },
    'gtja_016': {
        'calc': '(-1*TSMAX(RANK(CORR(RANK(VOLUME),RANK(VWAP),5)),5))',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': 'GTJA#16: 量价排名相关(IC=+0.047,夏普11.3)',
        'active': False,
    },
}


def ensure_factor_registry(con):
    """创建因子注册表"""
    con.execute("""
        CREATE TABLE IF NOT EXISTS factor_registry (
            factor_name VARCHAR PRIMARY KEY,
            group_name VARCHAR,
            horizon VARCHAR,
            description VARCHAR,
            calc_method VARCHAR,
            data_source VARCHAR,
            active BOOLEAN DEFAULT TRUE,
            weight DECIMAL(5,3) DEFAULT 0,
            created_at DATE DEFAULT CURRENT_DATE,
            updated_at DATE DEFAULT CURRENT_DATE
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS factor_ic_history (
            factor_name VARCHAR,
            month VARCHAR,
            rank_ic DECIMAL(10,6),
            p_value DECIMAL(10,6),
            n_stocks INTEGER,
            ret_horizon VARCHAR,
            PRIMARY KEY (factor_name, month, ret_horizon)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS factor_daily_values (
            date DATE,
            stock_code VARCHAR,
            factor_name VARCHAR,
            raw_value DOUBLE,
            zscore DOUBLE,
            PRIMARY KEY (date, stock_code, factor_name)
        )
    """)


def init_registry(con):
    """初始化因子注册表"""
    ensure_factor_registry(con)
    
    for name, cfg in FACTOR_DEFS.items():
        con.execute("""
            INSERT OR REPLACE INTO factor_registry 
            (factor_name, group_name, horizon, description, calc_method, data_source, active, weight)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [name, cfg['group'], cfg['horizon'], cfg['desc'],
              cfg['calc'], cfg['source'], cfg['active'], 0.0])
    
    # 初始化权重（等权）
    active = [n for n, c in FACTOR_DEFS.items() if c['active']]
    w = round(1.0 / len(active), 4) if active else 0
    for name in active:
        con.execute("UPDATE factor_registry SET weight = ? WHERE factor_name = ?", [w, name])
    
    print(f"✅ 因子注册表初始化完成: {len(FACTOR_DEFS)}个因子定义, {len(active)}个活跃")


def compute_factors(con, start_date='2025-05-30', end_date=None):
    """统一计算所有活跃因子"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    active = con.execute("SELECT factor_name FROM factor_registry WHERE active = TRUE").fetchdf()['factor_name'].tolist()
    print(f"计算 {len(active)} 个活跃因子: {active}")
    
    # 批量读原始数据
    daily = con.execute(f"""
        SELECT ts_code, trade_date, close, pct_chg/100.0 AS ret, vol/100.0 AS turn
        FROM daily
        WHERE date >= '{start_date}' AND date <= '{end_date}'
        ORDER BY stock_code, date
    """).fetchdf()
    
    val = con.execute(f"""
        SELECT stock_code, date, pe_ttm, pb, total_mv
        FROM stock_valuation
        WHERE date >= '{start_date}'
        ORDER BY stock_code, date
    """).fetchdf()
    
    roe_df = con.execute("""
        SELECT stock_code, MAX(report_date) AS rd, AVG(roe) AS roe
        FROM fin_income WHERE roe IS NOT NULL GROUP BY ts_code
    """).fetchdf()
    
    mf = con.execute(f"""
        SELECT stock_code, date, main_net/1e8 AS mf_net
        FROM money_flow WHERE date >= '{start_date}'
    """).fetchdf()
    
    print(f"  原始数据: {len(daily)}行日线, {len(val)}行估值, {len(roe_df)}行ROE, {len(mf)}行资金流")
    
    # 逐股票计算因子，边算边写（不攒内存）
    con.execute("DELETE FROM factor_daily_values")
    con.execute("BEGIN TRANSACTION")
    written = 0
    batch_commit = 0
    
    for code, grp in daily.groupby('stock_code', sort=False):
        grp = grp.sort_values('date').reset_index(drop=True)
        n = len(grp)
        if n < 60:
            continue
        
        rets = grp['ret'].values
        turns = grp['turn'].values
        closes = grp['close'].values
        dates = grp['date'].values
        
        def roll(arr, w, fn):
            out = np.full(n, np.nan)
            for i in range(w-1, n):
                out[i] = fn(arr[i-w+1:i+1])
            return out
        
        def r_prod(arr, w):
            return roll(arr, w, lambda x: np.nanprod(1 + x) - 1)
        
        def r_std(arr, w):
            return roll(arr, w, lambda x: np.nanstd(x) * np.sqrt(252))
        
        def r_mean(arr, w):
            return roll(arr, w, np.nanmean)
        
        factors = {
            'mom_5': r_prod(rets, 5),
            'mom_10': r_prod(rets, 10),
            'mom_20': r_prod(rets, 20),
            'mom_60': r_prod(rets, 60),
            'vol_20': r_std(rets, 20),
            'vol_60': r_std(rets, 60),
            'turn_5': r_mean(turns, 5),
            'turn_20': r_mean(turns, 20),
        }
        
        for i in range(n):
            date = dates[i]
            for fname in ['mom_5', 'mom_10', 'mom_20', 'mom_60', 'vol_20', 'vol_60', 'turn_5', 'turn_20']:
                if fname not in active:
                    continue
                val_f = factors[fname][i]
                if not np.isnan(val_f):
                    con.execute("INSERT OR REPLACE INTO factor_daily_values (date, stock_code, factor_name, raw_value) VALUES (?, ?, ?, ?)",
                              [date, code, fname, float(val_f)])
                    written += 1
        
        # 每10只commit一次，释放内存
        batch_commit += 1
        if batch_commit % 10 == 0:
            con.execute("COMMIT")
            con.execute("BEGIN TRANSACTION")
            if batch_commit % 500 == 0:
                print(f"  进度: {batch_commit}只股票, {written}条因子")
    
    con.execute("COMMIT")
    print(f"  量价因子写入完成: {written}条")
    
    # 估值因子（先写，趁内存还够）
    val_pivot = val.pivot_table(index=['stock_code', 'date'], values=['pe_ttm', 'pb', 'total_mv'])
    val_written = 0
    con.execute("BEGIN TRANSACTION")
    written_v = 0
    for (code, date), row in val_pivot.iterrows():
        date_str = str(date)[:10]
        if 'ep_ttm' in active and row.get('pe_ttm') and row['pe_ttm'] > 0:
            con.execute("INSERT OR REPLACE INTO factor_daily_values (date, stock_code, factor_name, raw_value) VALUES (?, ?, ?, ?)",
                      [date_str, code, 'ep_ttm', float(1.0 / row['pe_ttm'])])
            written_v += 1
        if 'bp' in active and row.get('pb') and row['pb'] > 0:
            con.execute("INSERT OR REPLACE INTO factor_daily_values (date, stock_code, factor_name, raw_value) VALUES (?, ?, ?, ?)",
                      [date_str, code, 'bp', float(1.0 / row['pb'])])
            written_v += 1
        if 'ln_cap' in active and row.get('total_mv') and row['total_mv'] > 0:
            con.execute("INSERT OR REPLACE INTO factor_daily_values (date, stock_code, factor_name, raw_value) VALUES (?, ?, ?, ?)",
                      [date_str, code, 'ln_cap', float(np.log(row['total_mv']))])
            written_v += 1
        if written_v % 50000 == 0:
            con.execute("COMMIT")
            con.execute("BEGIN TRANSACTION")
    con.execute("COMMIT")
    print(f"  估值因子写入完成: {written_v}条")
    
    # ROE
    if 'roe' in active:
        roe_written = 0
        con.execute("BEGIN TRANSACTION")
        for _, row in roe_df.iterrows():
            con.execute("INSERT OR REPLACE INTO factor_daily_values (date, stock_code, factor_name, raw_value) VALUES ('1970-01-01', ?, ?, ?)",
                      [row['stock_code'], 'roe', float(row['roe'])])
            roe_written += 1
        con.execute("COMMIT")
        print(f"  ROE因子写入完成: {roe_written}条")
    
    # 资金流
    if 'mf_net' in active:
        mf_written = 0
        con.execute("BEGIN TRANSACTION")
        for _, row in mf.iterrows():
            con.execute("INSERT OR REPLACE INTO factor_daily_values (date, stock_code, factor_name, raw_value) VALUES (?, ?, ?, ?)",
                      [str(row['date'])[:10], row['stock_code'], 'mf_net', float(row['mf_net'])])
            mf_written += 1
        con.execute("COMMIT")
        print(f"  资金流因子写入完成: {mf_written}条")
    
    # 释放估值/ROE/mf内存
    del val_pivot, val, roe_df, mf
    # 量价因子（放最后，因为数据量最大）
    con.execute("BEGIN TRANSACTION")
    written = 0
def compute_zscore(con, date=None):
    """逐日Z-score标准化"""
    if date:
        df = con.execute("""
            SELECT stock_code, factor_name, raw_value
            FROM factor_daily_values WHERE date = ? AND factor_name != 'roe'
        """, [date]).fetchdf()
    else:
        # 批量处理所有日期
        dates = con.execute("SELECT DISTINCT date FROM factor_daily_values WHERE date > '2000-01-01' ORDER BY date").fetchdf()['date'].tolist()
        for d in dates:
            compute_zscore(con, str(d)[:10])
        return
    
    if len(df) < 10:
        return
    
    for fname, grp in df.groupby('factor_name'):
        vals = grp['raw_value'].values
        # 去极值
        low, high = np.percentile(vals, [1, 99])
        vals = np.clip(vals, low, high)
        mean, std = np.nanmean(vals), np.nanstd(vals)
        if std > 0:
            zscores = (vals - mean) / std
            for code, z in zip(grp['stock_code'], zscores):
                con.execute("""
                    UPDATE factor_daily_values SET zscore = ?
                    WHERE date = ? AND stock_code = ? AND factor_name = ?
                """, [float(z), date, code, fname])


def update_ic(con, months_back=12):
    """计算各因子月度Rank IC"""
    end = datetime.now()
    for m in range(months_back):
        month_end = end - timedelta(days=30*m)
        month_start = month_end - timedelta(days=30)
        
        month_str = month_end.strftime('%Y-%m')
        
        # 取因子值和未来5日收益
        df = con.execute(f"""
            SELECT f.date, f.stock_code, f.factor_name, f.zscore,
                   (b5.close / a.close - 1) AS ret_5d
            FROM factor_daily_values f
            JOIN daily a ON f.ts_code=a.ts_code AND f.trade_date=a.trade_date
            LEFT JOIN daily b5 ON f.ts_code=b5.ts_code 
                AND b5.date = (SELECT MIN(trade_date) FROM daily WHERE ts_code=f.ts_code AND trade_date > f.trade_date + 4)
            WHERE f.date >= '{month_start.strftime('%Y-%m-%d')}' 
              AND f.date <= '{month_end.strftime('%Y-%m-%d')}'
              AND f.zscore IS NOT NULL
        """).fetchdf()
        
        if df.empty:
            continue
        
        for fname, grp in df.groupby('factor_name'):
            valid = grp[['zscore', 'ret_5d']].dropna()
            if len(valid) < 50:
                continue
            ic, pv = stats.spearmanr(valid['zscore'], valid['ret_5d'])
            con.execute("""
                INSERT OR REPLACE INTO factor_ic_history 
                (factor_name, month, rank_ic, p_value, n_stocks, ret_horizon)
                VALUES (?, ?, ?, ?, ?, '5d')
            """, [fname, month_str, round(ic, 6), round(pv, 6), len(valid)])
    
    print("✅ IC已更新")


def update_weights(con):
    """根据ICIR更新因子权重"""
    ic = con.execute("""
        SELECT factor_name, AVG(rank_ic) as mean_ic, 
               CASE WHEN STDDEV_SAMP(rank_ic) > 0 THEN AVG(rank_ic)/STDDEV_SAMP(rank_ic) ELSE 0 END as icir,
               COUNT(*) as months
        FROM factor_ic_history
        WHERE ret_horizon = '5d'
        GROUP BY factor_name
        HAVING COUNT(*) >= 3
    """).fetchdf()
    
    if ic.empty:
        print("⚠️ IC数据不足，无法更新权重")
        return
    
    # 权重 = max(0, abs(ICIR))
    ic['weight_raw'] = ic['icir'].abs().clip(0, None)
    total = ic['weight_raw'].sum()
    if total > 0:
        ic['weight'] = ic['weight_raw'] / total
        for _, row in ic.iterrows():
            con.execute("UPDATE factor_registry SET weight = ? WHERE factor_name = ?",
                       [round(row['weight'], 4), row['factor_name']])
    
    print("✅ 权重已更新")
    return ic


def generate_features(con, target_date=None):
    """为LightGBM生成特征矩阵"""
    if target_date is None:
        target_date = con.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    
    # 取所有活跃因子的最近值
    df = con.execute(f"""
        SELECT f.stock_code,
               MAX(CASE WHEN f.factor_name='mom_5' THEN f.zscore END) AS mom_5,
               MAX(CASE WHEN f.factor_name='mom_10' THEN f.zscore END) AS mom_10,
               MAX(CASE WHEN f.factor_name='mom_20' THEN f.zscore END) AS mom_20,
               MAX(CASE WHEN f.factor_name='mom_60' THEN f.zscore END) AS mom_60,
               MAX(CASE WHEN f.factor_name='vol_20' THEN f.zscore END) AS vol_20,
               MAX(CASE WHEN f.factor_name='vol_60' THEN f.zscore END) AS vol_60,
               MAX(CASE WHEN f.factor_name='turn_5' THEN f.zscore END) AS turn_5,
               MAX(CASE WHEN f.factor_name='turn_20' THEN f.zscore END) AS turn_20,
               MAX(CASE WHEN f.factor_name='ep_ttm' THEN f.zscore END) AS ep_ttm,
               MAX(CASE WHEN f.factor_name='bp' THEN f.zscore END) AS bp,
               MAX(CASE WHEN f.factor_name='ln_cap' THEN f.zscore END) AS ln_cap,
               MAX(CASE WHEN f.factor_name='roe' THEN f.zscore END) AS roe
        FROM factor_daily_values f
        WHERE f.date = '{target_date}' OR (f.factor_name='roe' AND f.date='1970-01-01')
        GROUP BY f.stock_code
    """).fetchdf()
    
    # 保存到临时表
    con.execute("DROP TABLE IF EXISTS tmp_feature_matrix")
    con.execute("CREATE TABLE tmp_feature_matrix AS SELECT * FROM df")
    print(f"✅ 特征矩阵: {len(df)}行, {len([c for c in df.columns if c != 'stock_code'])}个特征")
    print(f"  日期: {target_date}")
    return df


def show_status(con):
    """查看因子全景"""
    print("\n" + "=" * 70)
    print("📊 因子库全景")
    print("=" * 70)
    
    reg = con.execute("SELECT * FROM factor_registry ORDER BY active DESC, weight DESC").fetchdf()
    print(f"\n{'因子名':<12} {'分组':<12} {'活跃':<6} {'权重':<8} {'描述':<20}")
    print("-" * 70)
    for _, r in reg.iterrows():
        active = '✅' if r['active'] else '⏸'
        w = f"{r['weight']*100:.1f}%" if r['weight'] else '-'
        print(f"{r['factor_name']:<12} {r['group_name']:<12} {active:<6} {w:<8} {r['description']:<20}")
    
    ic = con.execute("""
        SELECT factor_name, AVG(rank_ic) as mean_ic, 
               AVG(rank_ic)/NULLIF(STDDEV_SAMP(rank_ic), 0) as icir,
               COUNT(*) as months
        FROM factor_ic_history WHERE ret_horizon='5d'
        GROUP BY factor_name ORDER BY icir DESC
    """).fetchdf()
    
    if not ic.empty:
        print(f"\n{'因子':<12} {'平均IC':<10} {'ICIR':<10} {'月数':<6}")
        print("-" * 50)
        for _, r in ic.iterrows():
            if r['months'] >= 3:
                print(f"{r['factor_name']:<12} {r['mean_ic']:<10.4f} {r['icir']:<10.3f} {r['months']:<6.0f}")
    
    cnt = con.execute("SELECT COUNT(*) FROM factor_daily_values").fetchone()[0]
    ic_cnt = con.execute("SELECT COUNT(*) FROM factor_ic_history").fetchone()[0]
    print(f"\n📁 factor_daily_values: {cnt}条")
    print(f"📁 factor_ic_history: {ic_cnt}条")


# ============================================================
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    
    con = duckdb.connect(str(TUSHARE_DB_PATH))
    con.execute("SET memory_limit='3GB'")
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    ensure_factor_registry(con)
    
    if cmd == 'init':
        init_registry(con)
    elif cmd == 'compute':
        compute_factors(con)
        compute_zscore(con)
    elif cmd == 'ic':
        update_ic(con, months_back=12)
        update_weights(con)
    elif cmd == 'features':
        generate_features(con)
    elif cmd == 'status':
        show_status(con)
    elif cmd == 'full':
        # 全流程
        compute_factors(con)
        compute_zscore(con)
        update_ic(con, months_back=12)
        update_weights(con)
        generate_features(con)
    else:
        print(f"未知命令: {cmd}")
        print("可用: init, compute, ic, features, status, full")
    
    con.close()


if __name__ == '__main__':
    main()
