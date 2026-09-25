#!/usr/bin/env python3
"""融合评分系统 v10 — 优化版，批量查询减少 SQL 调用"""
import duckdb, json, sys, numpy as np, lightgbm as lgb
from pathlib import Path
from datetime import date as dt_date

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feat_tushare import (
    compute_features, get_tushare_db, load_index_data,
    standardize_v6 as standardize_fn,
    N_BASE, GTJA_CODES, load_gtja_compact, get_gtja_value,
)

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'

REG20_MODEL = MODEL_DIR / 'lgb_reg_20d_v6_fixed.txt'
REG40_MODEL = MODEL_DIR / 'lgb_reg_40d_v6_fixed.txt'
NORM_STATS_20D = MODEL_DIR / 'v6_norm_stats_20d_v6_fixed.json'
NORM_STATS_40D = MODEL_DIR / 'v6_norm_stats_40d_v6_fixed.json'

W40, W20 = 0.70, 0.30
GTJA_NAMES = GTJA_CODES[:11]


def main():
    ref_date_str = None
    batch_start = None
    batch_end = None
    no_clear = '--no-clear' in sys.argv  # 不清空旧数据（用于分批）
    
    for i, a in enumerate(sys.argv):
        if a == '--date' and i+1 < len(sys.argv):
            ref_date_str = sys.argv[i+1]
        elif a == '--batch' and i+2 < len(sys.argv):
            batch_start = int(sys.argv[i+1])
            batch_end = int(sys.argv[i+2]) if sys.argv[i+2] else None
    
    today = dt_date.fromisoformat(ref_date_str) if ref_date_str else dt_date.today()
    today_str = today.isoformat()

    print("=" * 70)
    print("融合评分系统 v10 — feat_tushare_v6 (49 维管道)")
    print(f"  日期：{today_str} | 模型：v6_fixed(20d+40d) | 权重：40d×70% + 20d×30%")
    if batch_start:
        print(f"  批次模式：股票 {batch_start}-{batch_end or '末尾'}")
    print("=" * 70)

    # 加载模型
    reg20_model = None; stats20 = {}
    reg40_model = None; stats40 = {}
    
    if REG20_MODEL.exists():
        reg20_model = lgb.Booster(model_file=str(REG20_MODEL))
        print(f"✅ 20d 模型已加载 ({reg20_model.num_trees()}棵树)")
    if REG40_MODEL.exists():
        reg40_model = lgb.Booster(model_file=str(REG40_MODEL))
        print(f"✅ 40d 模型已加载 ({reg40_model.num_trees()}棵树)")
    
    if NORM_STATS_20D.exists():
        with open(NORM_STATS_20D) as f: stats20 = json.load(f)
    if NORM_STATS_40D.exists():
        with open(NORM_STATS_40D) as f: stats40 = json.load(f)

    from core.db import get_state_db, get_tushare_db
    conn_state = get_state_db()
    conn_tushare = get_tushare_db()

    # 指数数据
    idx_close_dict = load_index_data()
    print(f"✅ 指数数据：{len(idx_close_dict)}个交易日")

    # GTJA 因子
    gtja_lookup = load_gtja_compact()
    print(f"✅ GTJA 因子：{len(gtja_lookup) if gtja_lookup else 0}个")

    # 获取股票列表
    stocks = conn_tushare.execute("""
        SELECT ts_code, name FROM stock_basic 
        WHERE delist_date IS NULL
        ORDER BY ts_code
    """).fetchall()
    
    if batch_start:
        idx_start = batch_start - 1
        idx_end = batch_end if batch_end else len(stocks)
        stocks = stocks[idx_start:idx_end]
        print(f"\n📊 批次处理：{len(stocks)}只股票 (索引 {idx_start+1}-{idx_end})")
    else:
        if not no_clear:
            # 删当日旧数据（兼容两种日期格式）
            conn_state.execute(f"DELETE FROM signal_history WHERE REPLACE(date,'-','')='{today_str.replace('-','')}'")

    results = []
    
    # 预编译 SQL（减少解析开销）
    daily_sql = """
        SELECT date, close, open, high, low, 
               COALESCE(change_pct, 0), volume, amount
        FROM stock_daily WHERE stock_code=? ORDER BY date DESC LIMIT 120
    """
    
    for i, (code, name) in enumerate(stocks):
        if (i + 1) % 500 == 0:
            print(f"  已处理 {i+1}/{len(stocks)} 只...")
        
        code_short = code.split('.')[0]
        
        # 批量查询 K 线
        rows = conn_tushare.execute(daily_sql, [code_short]).fetchall()
        
        if not rows or len(rows) < 60:
            continue
        
        rows = rows[::-1]  # ascending
        closes_arr = [float(r[1]) for r in rows]
        lc = closes_arr[-1]
        
        # ML 特征计算
        feat_49d, _ = compute_449d_features(
            code, rows, conn_tushare, gtja_lookup, idx_close_dict
        )
        
        reg20_pred = reg40_pred = 0.0
        if feat_49d is not None and len(feat_49d) == 49:
            f_arr = np.nan_to_num(feat_49d.reshape(1, -1), nan=0.0)
            
            if reg20_model and stats20:
                f_std = standardize_fn(f_arr, stats20)
                try:
                    reg20_pred = float(reg20_model.predict(f_std)[0])
                except: pass
            
            if reg40_model and stats40:
                f_std_40 = standardize_fn(f_arr, stats40)
                try:
                    reg40_pred = float(reg40_model.predict(f_std_40)[0])
                except: pass
        
        reg20_score = max(0.0, min(100.0, (reg20_pred + 10) / 20 * 100))
        reg40_score = max(0.0, min(100.0, (reg40_pred + 10) / 20 * 100))
        composite = reg40_score * W40 + reg20_score * W20 if reg40_model else reg20_score
        
        dev120 = (lc / np.mean(closes_arr) - 1) * 100 if len(closes_arr) >= 120 else 0
        
        results.append({
            'code': code, 'name': name, 'price': lc,
            'composite': composite,
            'reg40_pred': reg40_pred, 'reg20_pred': reg20_pred,
            'dev120': dev120,
        })

    results.sort(key=lambda x: x['composite'], reverse=True)
    
    # 写入 DB
    if '--write-db' in sys.argv or '--db' in sys.argv:
        print(f"\n💾 写入信号历史...")
        
        inserted = 0
        for r in results:
            try:
                conn_state.execute("""
                    INSERT OR REPLACE INTO signal_history
                    (date, stock_code, stock_name, industry, fusion_score, reg20, reg40,
                     deviation120, final_score, fusion_avg, reg_pred, reg40_pred, is_limit_up)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    today_str, r['code'], r['name'], '',
                    round(r['composite'], 1),
                    round(r['reg20_pred'], 4), round(r['reg40_pred'], 4),
                    round(r['dev120'], 4),
                    round(r['composite'], 1), round(r['composite'], 1),
                    round(r['reg20_pred'], 4), round(r['reg40_pred'], 4), False,
                ])
                inserted += 1
                if inserted % 1000 == 0:
                    conn_state.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                if inserted <= 5:
                    print(f"  ⚠️ {r['code']}: {str(e)[:60]}")
        
        conn_state.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print(f"✅ 写入完成: {inserted} 条")

    conn_tushare.close()
    conn_state.close()
    
    # 输出前 20 名
    print(f"\n🏆 排名前 20:")
    for i, r in enumerate(results[:20], 1):
        print(f"  {i:2d}. {r['code']} {r['name'][:8]:8s} {r['composite']:6.0f}分")


def compute_449d_features(code, rows, conn, gtja_lookup, idx_close_dict):
    """简化版特征计算"""
    try:
        closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
        highs = np.array([float(r[3]) for r in rows], dtype=np.float64)
        lows = np.array([float(r[4]) for r in rows], dtype=np.float64)
        volumes = np.array([float(r[6]) if r[6] else 0.0 for r in rows], dtype=np.float64)
        pcts = np.array([float(r[5]) / 100.0 if r[5] else 0.0 for r in rows], dtype=np.float64)
        
        dates_str = [str(r[0])[:10].replace('-', '') for r in rows]
        
        val_row = conn.execute(
            "SELECT pe_ttm, pb, total_mv FROM stock_valuation WHERE stock_code=? ORDER BY date DESC LIMIT 1",
            [code]
        ).fetchone()
        
        val_dict = {}
        if val_row and len(val_row) >= 3:
            if val_row[0] and float(val_row[0]) > 0:
                val_dict['ep'] = 1.0 / float(val_row[0])
            if val_row[1] and float(val_row[1]) > 0:
                val_dict['bp'] = 1.0 / float(val_row[1])
            if val_row[2] and float(val_row[2]) > 0:
                val_dict['ln_cap'] = np.log(float(val_row[2]))
        
        feat_base = compute_features(
            closes.tolist(), highs.tolist(), lows.tolist(),
            volumes.tolist(), pcts.tolist(),
            idx_close_dict, val_dict
        )
        
        if gtja_lookup:
            gtja_vals = get_gtja_value(code, dates_str[-1], gtja_lookup)
        else:
            gtja_vals = [0.0] * 11
        
        if len(feat_base) != 38 or len(gtja_vals) != 11:
            return None, None
        
        feat_49d = np.concatenate([feat_base, np.array(gtja_vals[:11], dtype=np.float64)])
        return feat_49d, dates_str[-1]
    
    except Exception as e:
        return None, None


if __name__ == '__main__':
    main()
