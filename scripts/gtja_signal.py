#!/usr/bin/env python3
"""GTJA 合成信号 — 4因子 IC 加权排名归一化 + 回测验证

用法:
  python3 gtja_signal.py                 # 输出最新日期的 IC 加权信号
  python3 gtja_signal.py --mode equal    # 等权模式（旧）
  python3 gtja_signal.py --backtest      # 回测对比等权 vs IC 加权
"""
import os, sys, json, gzip, pickle
import numpy as np
from pathlib import Path
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_PATH = BASE / 'gtja_signal.json'

GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']

def load_gtja():
    if not GTJA_PKL.exists():
        print("❌ gtja_signals.pkl.gz 不存在")
        sys.exit(1)
    with gzip.open(GTJA_PKL, 'rb') as f:
        return pickle.load(f)

def compute_factor_score(gtja_data, factor_name, target_date_str):
    """对单个因子做横截面排名归一化 → {code: 0-100}"""
    if factor_name not in gtja_data:
        return {}
    df = gtja_data[factor_name]
    available = sorted(df.index)
    best_date = None
    for d in reversed(available):
        ds = str(d)[:10]
        if ds <= target_date_str:
            best_date = ds
            break
    if best_date is None:
        return {}
    
    row = df.loc[best_date]
    valid = row.dropna()
    if len(valid) < 100:
        return {}
    
    vals = valid.values
    mean_v, std_v = np.nanmean(vals), np.nanstd(vals)
    if std_v == 0 or np.isnan(std_v):
        return {}
    
    from scipy import stats
    z = (vals - mean_v) / std_v
    pcts = stats.rankdata(z) / len(z) * 100
    return {c: round(float(p), 2) for c, p in zip(valid.index, pcts)}

def get_ic_weights(gtja_data, target_date_str, conn, lookback=20):
    """计算各因子的滚动 IC 权重（仅正 IC 参与，全部为负→返回空）
    返回: {factor_name: weight} 或 {} 表示信号关闭
    """
    dates = conn.execute("""
        SELECT DISTINCT date FROM stock_daily 
        WHERE date <= ? ORDER BY date DESC LIMIT ?
    """, [target_date_str, lookback + 20 + 5]).fetchall()
    dates = [str(d[0])[:10] for d in dates]
    
    if len(dates) < lookback + 20:
        return {}  # 数据不够
    
    factor_ics = {}
    for gn in GTJA_4:
        if gn not in gtja_data:
            continue
        df = gtja_data[gn]
        daily_ics = []
        
        for i in range(lookback):
            t_date = dates[i]
            f_date = dates[i + 20] if i + 20 < len(dates) else None
            if f_date is None:
                continue
            
            # 因子值
            row = df.loc[df.index <= t_date]
            if row.empty:
                continue
            best = str(row.index[-1])[:10]
            vals = df.loc[best].dropna()
            if len(vals) < 50:
                continue
            
            codes = list(vals.index)[:300]
            placeholders = ','.join([f"'{c}'" for c in codes])
            rows = conn.execute(f"""
                SELECT a.stock_code, a.close as ct, b.close as cf
                FROM stock_daily a JOIN stock_daily b ON a.stock_code=b.stock_code
                WHERE a.date='{t_date}' AND b.date='{f_date}'
                AND a.stock_code IN ({placeholders})
            """).fetchall()
            
            sig, ret = [], []
            for r in rows:
                ct, cf = float(r[1]), float(r[2])
                if ct > 0 and cf > 0 and r[0] in vals.index:
                    sig.append(vals[r[0]])
                    ret.append((cf/ct - 1) * 100)
            
            if len(sig) < 30:
                continue
            from scipy import stats
            ic, _ = stats.spearmanr(sig, ret)
            daily_ics.append(ic)
        
        if daily_ics:
            factor_ics[gn] = np.mean(daily_ics)
    
    # 只保留正 IC
    positive = {k: max(0, v) for k, v in factor_ics.items()}
    total = sum(positive.values())
    if total == 0:
        return {}  # 全部负 → 信号关闭
    
    return {k: v/total for k, v in positive.items()}

def compute_composite(gtja_data, target_date_str, weights=None):
    """合成信号。weights=None=等权, weights=dict=IC加权, weights={}=信号关闭返回空"""
    if weights is not None and not weights:
        return {}  # IC全负，关闭信号
    
    factor_scores = {}
    for gn in GTJA_4:
        fs = compute_factor_score(gtja_data, gn, target_date_str)
        if fs:
            factor_scores[gn] = fs
    
    if not factor_scores:
        return {}
    
    all_codes = set()
    for fs in factor_scores.values():
        all_codes.update(fs.keys())
    
    if weights is None:
        w = {gn: 1.0/len(GTJA_4) for gn in GTJA_4}
    else:
        w = weights
    
    scores = {}
    for code in all_codes:
        vals, wts = [], []
        for gn in GTJA_4:
            if gn in factor_scores and gn in w:
                vals.append(factor_scores[gn].get(code, 50))
                wts.append(w[gn])
        if vals and sum(wts) > 0:
            scores[code] = round(sum(v*wt for v, wt in zip(vals, wts)) / sum(wts), 2)
    
    return scores

def compute_ic(gtja_data, days=90, ic_weighted=True):
    """回测 IC"""
    conn = duckdb.connect(str(DB), read_only=True)
    dates = conn.execute("""SELECT DISTINCT date FROM stock_daily WHERE date >= '2025-01-01' ORDER BY date""").fetchall()
    dates = [str(d[0])[:10] for d in dates]
    
    if len(dates) < 30:
        conn.close(); return None
    
    actual_days = min(days, len(dates) - 20)
    label = "IC加权" if ic_weighted else "等权"
    print(f"  可用 {len(dates)} 天，回测 {actual_days} 天 [{label}]")
    
    test_dates = dates[-actual_days-20:]
    ics = []
    signal_off_days = 0
    
    for i, dt in enumerate(test_dates[:actual_days]):
        if ic_weighted:
            w = get_ic_weights(gtja_data, dt, conn)
            if not w:
                signal_off_days += 1
                continue
            scores = compute_composite(gtja_data, dt, w)
        else:
            scores = compute_composite(gtja_data, dt, None)
        
        if len(scores) < 50:
            continue
        
        future_idx = i + 20
        if future_idx >= len(test_dates):
            continue
        future_dt = test_dates[future_idx]
        
        codes = list(scores.keys())[:500]
        placeholders = ','.join([f"'{c}'" for c in codes])
        rows = conn.execute(f"""
            SELECT a.stock_code, a.close, b.close
            FROM stock_daily a JOIN stock_daily b ON a.stock_code=b.stock_code
            WHERE a.date='{dt}' AND b.date='{future_dt}'
            AND a.stock_code IN ({placeholders})
        """).fetchall()
        
        if len(rows) < 30:
            continue
        
        sig, ret = [], []
        for r in rows:
            ct, cf = float(r[1]), float(r[2])
            if ct > 0 and cf > 0:
                sig.append(scores.get(r[0], 50))
                ret.append((cf/ct - 1) * 100)
        
        if len(sig) < 30:
            continue
        
        from scipy import stats
        ic, _ = stats.spearmanr(sig, ret)
        ics.append((dt, ic, len(sig)))
        
        if (i + 1) % 20 == 0:
            avg = np.mean([x[1] for x in ics]) if ics else 0
            print(f"  进度 {i+1}/{actual_days}  avg IC={avg:+.4f} 关闭{signal_off_days}天")
    
    conn.close()
    return ics, signal_off_days

def main():
    gtja_data = load_gtja()
    print(f"✅ GTJA 因子已加载")
    
    mode = 'ic'  # 默认 IC 加权
    for a in sys.argv:
        if a == '--mode' or a == '-m':
            idx = sys.argv.index(a)
            if idx + 1 < len(sys.argv):
                mode = sys.argv[idx+1]
    
    if '--backtest' in sys.argv:
        print(f"\n🔬 回测对比: 等权 vs IC 加权")
        print("=" * 60)
        
        # 等权
        print("\n📊 等权模式:")
        ics_eq, _ = compute_ic(gtja_data, days=90, ic_weighted=False)
        if ics_eq:
            ic_vals = [x[1] for x in ics_eq]
            eq_ic = np.mean(ic_vals)
            eq_sharpe = np.mean(ic_vals)/np.std(ic_vals) if np.std(ic_vals)>0 else 0
            eq_pos = sum(1 for x in ic_vals if x>0)/len(ic_vals)*100
            print(f"  平均IC={eq_ic:+.4f}  夏普={eq_sharpe:+.2f}  正向率={eq_pos:.0f}%")
        
        # IC 加权
        print("\n📊 IC 加权模式:")
        ics_iw, off_days = compute_ic(gtja_data, days=90, ic_weighted=True)
        if ics_iw:
            ic_vals = [x[1] for x in ics_iw]
            iw_ic = np.mean(ic_vals)
            iw_sharpe = np.mean(ic_vals)/np.std(ic_vals) if np.std(ic_vals)>0 else 0
            iw_pos = sum(1 for x in ic_vals if x>0)/len(ic_vals)*100
            print(f"  平均IC={iw_ic:+.4f}  夏普={iw_sharpe:+.2f}  正向率={iw_pos:.0f}%  关闭{off_days}天")
        
        # 对比
        if ics_eq and ics_iw:
            print(f"\n📊 对比:")
            print(f"  IC:  {eq_ic:+.4f} → {iw_ic:+.4f}  ({'✅' if iw_ic > eq_ic else '❌'})")
            print(f"  夏普: {eq_sharpe:+.2f} → {iw_sharpe:+.2f}  ({'✅' if iw_sharpe > eq_sharpe else '❌'})")
            if iw_ic > eq_ic:
                print(f"\n✅ IC 加权优于等权，建议采用")
            else:
                print(f"\n⚠️ IC 加权未改善，保持等权")
        
        if off_days > 90 * 0.3:
            print(f"\n⚠️ 信号关闭天数过多 ({off_days})，GTJA 信号可靠性存疑")
    
    else:
        conn = duckdb.connect(str(DB), read_only=True)
        latest = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
        latest_str = str(latest)[:10]
        
        print(f"📅 计算日期: {latest_str} 模式: {mode}")
        
        if mode == 'equal':
            scores = compute_composite(gtja_data, latest_str, None)
        else:
            w = get_ic_weights(gtja_data, latest_str, conn)
            if w:
                print(f"  IC权重: {', '.join(f'{k}={v:.2f}' for k,v in sorted(w.items()))}")
                scores = compute_composite(gtja_data, latest_str, w)
            else:
                print(f"  ⚠️ IC 全为负，GTJA 信号关闭，回归 100%")
                scores = {}
        
        conn.close()
        
        print(f"✅ 计算完成: {len(scores)} 只")
        if scores:
            top = sorted(scores.items(), key=lambda x: -x[1])[:10]
            print(f"\n  TOP 10:")
            for code, sc in top:
                print(f"    {code}: {sc:.1f}")
        
        with open(OUT_PATH, 'w') as f:
            json.dump({'date': latest_str, 'scores': scores, 'mode': mode}, f, ensure_ascii=False)
        print(f"\n💾 已保存: {OUT_PATH}")

if __name__ == '__main__':
    main()
