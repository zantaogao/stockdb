#!/usr/bin/env python3
"""
快速因子Bench — 从Vibe-Trading调因子，在内存中计算IC，不写入DB
"""
import os, sys, time, importlib
import duckdb, numpy as np, pandas as pd
from scipy import stats

HOME = os.path.expanduser('~')
DB = os.path.join(HOME, '.hermes/stockdb/stock.db')

def build_panel(start_date='2024-01-01'):
    con = duckdb.connect(DB)
    df = con.execute(f"""
        SELECT stock_code, date, open, close, high, low, volume, amount,
               change_pct/100.0 as returns
        FROM stock_daily WHERE date >= '{start_date}' ORDER BY date, stock_code
    """).fetchdf()
    con.close()
    
    panel = {}
    for col in ['open', 'close', 'high', 'low', 'volume', 'amount', 'returns']:
        panel[col] = df.pivot_table(index='date', columns='stock_code', values=col)
    panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)
    # 未来5日收益（标签）
    panel['ret_future'] = panel['close'].pct_change(5).shift(-5)
    return panel


def bench_zoo(zoo_name='gtja191', max_factors=None, top_n=20, start_from=1):
    """计算整个zoo的因子IC，返回排名"""
    meta = {
        'gtja191': ('src.factors.zoo.gtja191', 191, '国泰君安'),
        'alpha101': ('src.factors.zoo.alpha101', 101, 'Kakushadze'),
        'qlib158': ('src.factors.zoo.qlib158', 158, 'Qlib'),
    }
    module_path, total, label = meta[zoo_name]
    
    print(f"Bench {label} ({total}个因子)...", flush=True)
    
    t0 = time.time()
    panel = build_panel()
    print(f"Panel: {panel['close'].shape}, {time.time()-t0:.0f}s", flush=True)
    
    results = []
    limit = max_factors or total
    csv_path = os.path.join(HOME, '.hermes/stockdb', f'{zoo_name}_bench.csv')
    
    # 如果已有部分结果，跳过已完成的
    done = set()
    if os.path.exists(csv_path) and start_from == 1:
        existing = pd.read_csv(csv_path)
        done = set(existing['id'].tolist())
        print(f"  已有{len(done)}个结果", flush=True)
    
    for i in range(start_from, limit + 1):
        alpha_id = f"alpha_{i:03d}"
        full_id = f"{zoo_name}_{alpha_id}"
        if full_id in done:
            continue
        try:
            mod = importlib.import_module(f"{module_path}.{alpha_id}")
        except (ImportError, ModuleNotFoundError):
            continue
        
        t1 = time.time()
        try:
            signal = mod.compute(panel)
        except Exception as e:
            print(f"  [{i}/{limit}] {alpha_id}: ❌ {str(e)[:50]}", flush=True)
            continue
        
        if signal is None or signal.empty:
            continue
        
        # 计算每日IC
        ics = []
        for dt in signal.index:
            row = signal.loc[dt].dropna()
            ret = panel['ret_future'].loc[dt].dropna()
            # 取交集
            common = row.index.intersection(ret.index)
            if len(common) < 30:
                continue
            x, y = row[common].values, ret[common].values
            if np.std(x) == 0 or np.std(y) == 0:
                continue
            ics.append(stats.spearmanr(x, y)[0])
        
        if len(ics) < 10:
            continue
        
        mean_ic = np.mean(ics)
        sharpe = mean_ic / np.std(ics) * np.sqrt(252) if np.std(ics) > 0 else 0
        pos_pct = (np.array(ics) > 0).mean() * 100
        
        results.append({
            'id': f"{zoo_name}_{alpha_id}",
            'daily_ic': mean_ic,
            'sharpe': sharpe,
            'pos_pct': pos_pct,
            'days': len(ics),
            'time': time.time() - t1,
        })
        
        print(f"  [{i}/{limit}] {alpha_id}: IC={mean_ic:+.4f} 夏普={sharpe:.2f} ({time.time()-t1:.1f}s)", flush=True)
        
        # 增量保存（追加模式）
        pd.DataFrame([results[-1]]).to_csv(csv_path, mode='a', header=not os.path.exists(csv_path), index=False)
    
    # 排名
    results.sort(key=lambda x: -abs(x['daily_ic']))
    print(f"\n{'='*90}")
    print(f"{'排名':>4} {'因子ID':25s} {'Daily IC':>9} {'夏普':>7} {'胜率':>6} {'天数':>5} {'耗时':>5}")
    print(f"{'='*90}")
    for i, r in enumerate(results[:top_n], 1):
        print(f"{i:4d} {r['id']:25s} {r['daily_ic']:>+9.4f} {r['sharpe']:>7.2f} {r['pos_pct']:>5.0f}% {r['days']:5d} {r['time']:5.1f}s")
    
    # 保存
    pd.DataFrame(results).to_csv(f"{HOME}/.hermes/stockdb/{zoo_name}_bench.csv", index=False)
    print(f"\n总耗时: {time.time()-t0:.0f}s")
    print(f"有效因子: {len(results)}/{limit}")
    
    # 自动注册到factor_library
    registry_path = os.path.join(os.path.dirname(__file__), 'factor_library.py')
    if os.path.exists(registry_path):
        with open(registry_path) as f:
            content = f.read()
        
        # 生成新的GTJA因子定义块
        new_defs = "\n    # --- GTJA Alpha因子（Vibe-Trading计算，A股有效）---\n"
        added = 0
        for r in sorted(results, key=lambda x: -abs(x['daily_ic'])):
            if abs(r['daily_ic']) < 0.02:
                continue
            name = r['id'].replace('gtja191_', 'gtja_')
            ic = r['daily_ic']
            fname = name if ic > 0 else f"{name}_inv"
            ic_display = abs(ic)
            if name not in content and fname not in content:
                new_defs += f"""    '{fname}': {{
        'calc': 'GTJA因子(自动注册)',
        'source': 'vibe_trading',
        'horizon': 'medium',
        'group': 'gtja',
        'desc': '{'GTJA#' + name.split('_')[1] + ('取反' if ic<0 else '')}(IC=+{ic_display:.3f},夏普={r["sharpe"]:.1f})',
        'active': False,
    }},
"""
                added += 1
        
        if added > 0:
            # 找到最后一个因子定义的位置插进去
            marker = "    # --- 资金流因子"
            insert_pos = content.find(marker)
            if insert_pos > 0:
                # 找到这个块结束的位置（在mf_net定义后的 } 后面）
                block_end = content.find('}', insert_pos)
                block_end = content.find('}', block_end + 1) 
                block_end = content.find('}', block_end + 1) + 1
                new_content = content[:block_end] + new_defs + content[block_end:]
                with open(registry_path, 'w') as f:
                    f.write(new_content)
                print(f"  已注册{added}个新因子到factor_library.py")
            else:
                print("  未找到插入位置")
        else:
            print("  无新因子需要注册")
    
    return results


if __name__ == '__main__':
    zoo = sys.argv[1] if len(sys.argv) > 1 else 'gtja191'
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    start = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    bench_zoo(zoo, max_factors=limit, start_from=start)
