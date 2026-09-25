#!/usr/bin/env python3
"""
因子Bench框架 + Walk-Forward验证
用法:
  python3 factor_bench.py list          # 列出所有因子
  python3 factor_bench.py bench         # 跑所有因子bench (IC+分组)
  python3 factor_bench.py walkforward   # Walk-Forward滚动验证
  python3 factor_bench.py compare       # 对比新旧因子集
"""

import os, sys, json, math
from datetime import datetime, timedelta
import duckdb
import numpy as np
import pandas as pd
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

HOME = os.path.expanduser('~')
# 自动检测：如果在PC上（有C:盘），用PC路径
if sys.platform == 'win32' or os.path.exists('C:\\'):
    DB = r"C:\Users\pumma\factor_lib\stock.db"
else:
    DB = os.path.join(HOME, '.hermes/stockdb/stock.db')


def _get_factor_values(con, factor_names, start_date='2024-01-01', end_date=None):
    """从factor_daily_values拉取因子值，返回(date, code, factor_values)矩阵"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    names_str = ','.join([f"'{n}'" for n in factor_names])
    sql = f"""
        SELECT f.date, f.stock_code, f.factor_name, f.zscore,
               (b.close / a.close - 1) as ret_future
        FROM factor_daily_values f
        JOIN stock_daily a ON f.stock_code = a.stock_code AND f.date = a.date
        LEFT JOIN stock_daily b ON f.stock_code = b.stock_code
            AND b.date = (SELECT MIN(date) FROM stock_daily 
                          WHERE stock_code = f.stock_code AND date > f.date + 4)
        WHERE f.zscore IS NOT NULL AND f.date >= '{start_date}'
          AND f.factor_name IN ({names_str})
        ORDER BY f.date, f.stock_code
    """
    df = con.execute(sql).fetchdf()
    if len(df) == 0:
        return None
    
    # Pivot: index=[date, stock_code], columns=factor_name, values=zscore
    idx_cols = ['date', 'stock_code', 'ret_future']
    pv = df.pivot_table(index=idx_cols, columns='factor_name', values='zscore').reset_index()
    pv = pv.dropna(subset=factor_names)  # 只保留所有因子都有值的行
    return pv


def _daily_ic(grp, factor_name, ret_col='ret_future'):
    """计算单日IC"""
    if len(grp) < 30:
        return None
    x = grp[factor_name].values
    y = grp[ret_col].values
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return stats.spearmanr(x, y)[0]


def _decile_returns(grp, factor_name, ret_col='ret_future'):
    """计算分组收益"""
    if len(grp) < 50:
        return {}
    grp = grp.sort_values(factor_name, ascending=False)
    n = len(grp)
    results = {}
    for d in range(10):
        s = d * n // 10
        e = (d + 1) * n // 10
        results[f'D{d+1}'] = grp.iloc[s:e][ret_col].mean()
    results['spread'] = results['D1'] - results['D10']
    results['mono'] = all(results[f'D{i}'] > results[f'D{i+1}'] for i in range(1, 10))
    return results


def bench_factor(pv, factor_name, ret_col='ret_future'):
    """对一个因子跑完整bench"""
    if factor_name not in pv.columns:
        return None
    
    result = {'factor': factor_name}
    
    # 1. 每日IC
    daily_ics = pv.groupby('date', group_keys=False).apply(
        lambda g: _daily_ic(g, factor_name, ret_col))
    daily_ics = daily_ics.dropna()
    result['daily_ic_mean'] = daily_ics.mean()
    result['daily_ic_std'] = daily_ics.std()
    result['daily_ic_sharpe'] = daily_ics.mean() / daily_ics.std() * np.sqrt(252) if daily_ics.std() > 0 else 0
    result['daily_ic_positive_pct'] = (daily_ics > 0).mean() * 100
    result['daily_ic_days'] = len(daily_ics)
    
    # 2. 总体IC（横截面）
    ic_all = _daily_ic(pv, factor_name, ret_col)
    result['overall_ic'] = ic_all
    
    # 3. 分组收益
    deciles = pv.groupby('date', group_keys=False).apply(
        lambda g: _decile_returns(g, factor_name, ret_col))
    
    # 聚合
    decile_df = pd.DataFrame(deciles.tolist())
    for d in range(1, 11):
        result[f'D{d}'] = decile_df[f'D{d}'].mean() * 100
    result['spread'] = decile_df['spread'].mean() * 100
    result['mono_pct'] = decile_df['mono'].mean() * 100
    
    return result


def _walkforward_split(dates, n_train_months=12, n_test_months=3):
    """生成Walk-Forward滚动窗口"""
    dates = sorted(set(dates))
    splits = []
    
    # 先确定最小/最大日期
    min_date = datetime.strptime(str(dates[0])[:10], '%Y-%m-%d')
    max_date = datetime.strptime(str(dates[-1])[:10], '%Y-%m-%d')
    
    # 从最小日期+n_train_months开始，每3个月一个窗口
    cursor = min_date + timedelta(days=n_train_months * 30)
    while cursor < max_date:
        train_end = cursor
        test_end = cursor + timedelta(days=n_test_months * 30)
        if test_end > max_date:
            break
        
        train_start = cursor - timedelta(days=n_train_months * 30)
        test_start = cursor
        
        train_dates = [d for d in dates if train_start <= datetime.strptime(str(d)[:10], '%Y-%m-%d') <= train_end]
        test_dates = [d for d in dates if test_start <= datetime.strptime(str(d)[:10], '%Y-%m-%d') <= test_end]
        
        splits.append({
            'train': [str(d)[:10] for d in train_dates],
            'test': [str(d)[:10] for d in test_dates],
            'label': f'{train_start.strftime("%Y%m")}-{test_start.strftime("%Y%m")}'
        })
        
        cursor += timedelta(days=n_test_months * 30)
    
    return splits


def bench_factor_walkforward(pv, factor_name, splits, ret_col='ret_future'):
    """Walk-Forward验证一个因子"""
    if factor_name not in pv.columns:
        return None
    
    results = []
    for split in splits:
        test = pv[pv['date'].isin(split['test'])]
        if len(test) < 100:
            continue
        
        ic = _daily_ic(test, factor_name, ret_col)
        dec = _decile_returns(test, factor_name, ret_col)
        
        results.append({
            'window': split['label'],
            'ic': ic,
            'spread': dec.get('spread', 0) * 100 if dec.get('spread') else 0,
            'mono': dec.get('mono', False),
            'test_days': test['date'].nunique(),
            'test_stocks': len(test)
        })
    
    return results


# ── CLI ──
def cmd_list():
    """列出所有因子"""
    con = duckdb.connect(DB)
    factors = con.execute("""
        SELECT factor_name, group_name, description, active, horizon
        FROM factor_registry ORDER BY group_name, factor_name
    """).fetchdf()
    con.close()
    
    print(f"\n因子注册表: {len(factors)}个因子")
    print(f"{'='*80}")
    print(f"{'因子名':20s} {'分组':15s} {'描述':30s} {'活跃':6s}")
    print(f"{'='*80}")
    for _, r in factors.iterrows():
        active = '✅' if r['active'] else '❌'
        print(f"{r['factor_name']:20s} {r['group_name']:15s} {str(r['description']):30s} {active}")
    return factors


def cmd_bench(factor_names=None):
    """跑所有因子bench"""
    con = duckdb.connect(DB)
    
    if factor_names is None:
        factors = con.execute(
            "SELECT DISTINCT f.factor_name FROM factor_registry f "
            "JOIN factor_daily_values d ON f.factor_name=d.factor_name WHERE f.active=TRUE"
        ).fetchdf()['factor_name'].tolist()
        if not factors:
            factors = con.execute(
                "SELECT DISTINCT factor_name FROM factor_daily_values"
            ).fetchdf()['factor_name'].tolist()
    else:
        factors = factor_names
    
    print(f"加载因子数据 ({len(factors)}个)...", flush=True)
    pv = _get_factor_values(con, factors, start_date='2024-01-01')
    if pv is None:
        print("无数据")
        con.close()
        return
    
    print(f"数据: {len(pv)}行, {pv['date'].nunique()}天\n", flush=True)
    
    results = []
    for f in factors:
        r = bench_factor(pv, f)
        if r:
            results.append(r)
        print(f"  {f:15s}", end='', flush=True)
        if r:
            print(f" IC={r['daily_ic_mean']:.4f} 多空={r['spread']:+.2f}% 单调={r['mono_pct']:.0f}%", flush=True)
        else:
            print(" 数据不足", flush=True)
    
    con.close()
    
    # 汇总表
    print(f"\n{'='*100}")
    print(f"{'因子':18s} {'Daily IC':>8} {'IC夏普':>7} {'IC胜率':>7} {'多空%':>8} {'D1%':>7} {'D10%':>7} {'单调%':>6}")
    print(f"{'='*100}")
    results.sort(key=lambda x: -abs(x['daily_ic_mean']))
    for r in results:
        print(f"{r['factor']:18s} {r['daily_ic_mean']:>+8.4f} {r['daily_ic_sharpe']:>7.2f} "
              f"{r['daily_ic_positive_pct']:>6.0f}% {r['spread']:>+7.2f}% "
              f"{r['D1']:>+6.2f}% {r['D10']:>+6.2f}% {r['mono_pct']:>5.0f}%")
    
    return results


def cmd_walkforward():
    """Walk-Forward滚动验证"""
    con = duckdb.connect(DB)
    factors = con.execute(
        "SELECT DISTINCT factor_name FROM factor_daily_values WHERE factor_name IS NOT NULL"
    ).fetchdf()['factor_name'].tolist()
    if not factors:
        print("因子表无数据")
        con.close()
        return
    
    print(f"加载因子数据...", flush=True)
    pv = _get_factor_values(con, factors, start_date='2024-01-01')
    if pv is None:
        con.close()
        return
    
    dates = sorted(pv['date'].unique())
    print(f"数据: {len(pv)}行, {len(dates)}天", flush=True)
    
    splits = _walkforward_split(dates, n_train_months=12, n_test_months=3)
    print(f"Walk-Forward: {len(splits)}个窗口\n", flush=True)
    
    all_results = {}
    for f in factors:
        wf = bench_factor_walkforward(pv, f, splits)
        if wf:
            all_results[f] = wf
    
    # 汇总
    print(f"{'='*120}")
    print(f"{'因子':18s} {'窗口':>8} {'IC':>8} {'多空%':>8}")
    print(f"{'='*120}")
    for f, wfs in all_results.items():
        for w in wfs:
            ic_str = f"{w['ic']:.4f}" if w['ic'] is not None else "N/A"
            print(f"{f:18s} {w['window']:>8s} {ic_str:>8} {w['spread']:>+7.2f}%")
        print()
    
    con.close()
    return all_results


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    
    if cmd == 'list':
        cmd_list()
    elif cmd == 'bench':
        cmd_bench()
    elif cmd == 'walkforward':
        cmd_walkforward()
    else:
        print(f"未知命令: {cmd}")
        print("用法: python3 factor_bench.py [list|bench|walkforward]")
