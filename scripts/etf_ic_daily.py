#!/usr/bin/env python3
"""ETF 模型每日 IC 计算 — 验证模型预测能力"""
import sys, json, sqlite3, numpy as np
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import get_tushare_db
from core.scoring import score_etf

STATE_DB = Path(__file__).resolve().parent.parent / 'signals.db'  # v2温层

def compute_etf_ic(signal_date_str=None):
    """计算ETF模型IC：评分 vs 次日收益"""
    if signal_date_str is None:
        signal_date_str = datetime.now().strftime('%Y%m%d')
    
    tushare = get_tushare_db()
    
    # 获取有足够数据(150+天)的ETF
    rows = tushare.execute("""
        SELECT f.ts_code, f.name 
        FROM fund_basic f 
        INNER JOIN (
            SELECT ts_code, COUNT(*) as cnt 
            FROM fund_daily GROUP BY ts_code HAVING cnt >= 150
        ) d ON f.ts_code = d.ts_code
        ORDER BY d.cnt DESC
    """).fetchall()
    
    if not rows:
        return {"error": "无ETF数据"}
    
    # 获取当日净值
    ts_codes = [r[0] for r in rows]
    placeholders = ','.join(['?' for _ in ts_codes])
    prices = tushare.execute(f"""
        SELECT ts_code, close FROM fund_daily 
        WHERE trade_date = ? AND ts_code IN ({placeholders})
    """, (signal_date_str,) + tuple(ts_codes)).fetchall()
    
    if not prices:
        # 使用最新交易日
        latest = tushare.execute("SELECT MAX(trade_date) FROM fund_daily").fetchone()
        if not latest or not latest[0]:
            return {"error": "无净值数据"}
        prices = tushare.execute(f"""
            SELECT ts_code, close FROM fund_daily 
            WHERE trade_date = ? AND ts_code IN ({placeholders})
        """, (str(latest[0]),) + tuple(ts_codes)).fetchall()
        signal_date_str = str(latest[0])
    
    if not prices:
        return {"error": f"当日无净值数据：{signal_date_str}"}
    
    price_map = {p[0]: float(p[1]) for p in prices}
    
    # 获取次日(下个交易日)价格
    next_day = tushare.execute("""
        SELECT MIN(trade_date) FROM fund_daily 
        WHERE trade_date > ?
    """, (signal_date_str,)).fetchone()
    
    if next_day and next_day[0]:
        next_date = str(next_day[0])
    else:
        # 没有次日数据，尝试回退到前一个交易日
        prev_day = tushare.execute("""
            SELECT MAX(trade_date) FROM fund_daily 
            WHERE trade_date < ?
        """, (signal_date_str,)).fetchone()
        if prev_day and prev_day[0]:
            return compute_etf_ic(str(prev_day[0]))
        return {"error": f"无法获取次日交易数据（最新日期 {signal_date_str}）"}
    
    next_prices = tushare.execute(f"""
        SELECT ts_code, close FROM fund_daily 
        WHERE trade_date = ? AND ts_code IN ({placeholders})
    """, (next_date,) + tuple(ts_codes)).fetchall()
    next_map = {p[0]: float(p[1]) for p in next_prices}
    
    # 评分 + IC 计算
    scores = []
    returns = []
    scored_count = 0
    
    for ts_code, name in rows:
        if ts_code not in price_map or ts_code not in next_map:
            continue
        
        p1 = price_map[ts_code]
        p2 = next_map[ts_code]
        ret = (p2 - p1) / p1 * 100
        
        try:
            sr = score_etf(ts_code, as_of_date=signal_date_str)  # as_of 截止：评分只用信号日及之前数据，防未来泄漏（2026-08-03）
            if sr and sr['score'] is not None:
                scores.append(sr['score'])
                returns.append(ret)
                scored_count += 1
        except:
            pass
    
    if len(scores) < 10:
        return {"error": f"有效样本太少：{scored_count}/{len(rows)}"}
    
    scores_arr = np.array(scores)
    returns_arr = np.array(returns)
    
    # 1. Pearson IC（跟以前兼容）
    ic_pearson = float(np.corrcoef(scores_arr, returns_arr)[0, 1])
    
    # 2. Spearman IC（跟股票模型一致）
    from scipy.stats import spearmanr
    ic_spearman, pval = spearmanr(scores_arr, returns_arr)
    ic_spearman = float(ic_spearman)
    
    # 3. 20d forward IC（匹配模型训练目标）
    # 2026-08-08 修: 原实现取 MIN(trade_date)=signal_date 后第一个基金交易日(=次日收益) → ic_20d 恒等于 ic_spearman,
    # 列名误导。改为取第 20 个基金交易日 (ORDER BY LIMIT 1 OFFSET 19)。
    # 2026-08-11 再修: 上一版 OFFSET 19 取的是"第 20 行"——fund_daily 每天 2000+ 行,
    # 第 20 行仍落在首个后续交易日 → ic_20d 依旧恒等于 ic_spearman（8/8 起所有行假数据）。
    # 正确: SELECT DISTINCT trade_date 后 OFFSET 19 才是第 20 个交易日。
    ic_20d = 0.0
    try:
        next_20d = tushare.execute("""
            SELECT DISTINCT trade_date FROM fund_daily 
            WHERE trade_date > ? AND trade_date <= ?
            ORDER BY trade_date LIMIT 1 OFFSET 19
        """, (signal_date_str, str(int(signal_date_str) + 400))).fetchone()
        if next_20d and next_20d[0]:
            nd20 = str(next_20d[0])
            next20_prices = tushare.execute(f"""
                SELECT ts_code, close FROM fund_daily 
                WHERE trade_date = ? AND ts_code IN ({placeholders})
            """, (nd20,) + tuple(ts_codes)).fetchall()
            next20_map = {p[0]: float(p[1]) for p in next20_prices}
            
            ret20_list = []
            for ts_code, name in rows:
                p1 = price_map.get(ts_code)
                p20 = next20_map.get(ts_code)
                if p1 and p20 and p1 > 0:
                    ret20_list.append((p20 - p1) / p1 * 100)
            
            if len(ret20_list) >= 30 and len(ret20_list) == len(scores):
                ic_20d = float(spearmanr(scores_arr, np.array(ret20_list))[0])
    except:
        pass
    
    # 分组收益
    idx = np.argsort(scores_arr)[::-1]
    sorted_returns = returns_arr[idx]
    top_n = max(1, len(sorted_returns) // 10)
    top_ret = float(np.mean(sorted_returns[:top_n]))
    bottom_ret = float(np.mean(sorted_returns[-top_n:]))
    
    result = {
        "calc_date": datetime.now().strftime('%Y%m%d'),
        "signal_date": signal_date_str,
        "sample_size": scored_count,
        "total_etfs": len(rows),
        "ic_etf": round(ic_pearson, 4),
        "ic_spearman": round(ic_spearman, 4),
        "ic_20d": round(ic_20d, 4),
        "top_ret": round(top_ret, 4),
        "bottom_ret": round(bottom_ret, 4),
        "ic_diff": round(top_ret - bottom_ret, 4),
    }
    
    # 写入 signals.db（保留旧名称兼容，增加 Spearman 和 20d 字段）
    conn = sqlite3.connect(str(STATE_DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS etf_ic (
            calc_date DATE NOT NULL,
            signal_date DATE NOT NULL,
            sample_size INTEGER,
            ic_etf DOUBLE,
            ic_spearman DOUBLE DEFAULT 0,
            ic_20d DOUBLE DEFAULT 0,
            top_ret DOUBLE,
            bottom_ret DOUBLE,
            ic_diff DOUBLE,
            PRIMARY KEY (calc_date, signal_date)
        )
    """)
    # 加新列（旧表可能没有）
    for col in ['ic_spearman', 'ic_20d']:
        try:
            conn.execute(f"ALTER TABLE etf_ic ADD COLUMN {col} DOUBLE DEFAULT 0")
        except:
            pass
    # 2026-08-08 防重复行: 先删同 signal_date 旧行（含不同 calc_date 的回退产物——
    # 主键是 (calc_date, signal_date)，update_etf 失败日回退写旧 signal_date 会产生多行）
    conn.execute("DELETE FROM etf_ic WHERE signal_date = ?", (result['signal_date'],))
    conn.execute("""
        INSERT OR REPLACE INTO etf_ic (calc_date, signal_date, sample_size, ic_etf, ic_spearman, ic_20d, top_ret, bottom_ret, ic_diff)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result['calc_date'], result['signal_date'],
        result['sample_size'], result['ic_etf'],
        result['ic_spearman'], result['ic_20d'],
        result['top_ret'], result['bottom_ret'], result['ic_diff']
    ))
    conn.commit()
    conn.close()
    
    return result

if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    result = compute_etf_ic(date_arg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
