#!/usr/bin/env python3
"""融合评分系统 v10 — 带详细计时"""
import duckdb, json, sys, time, numpy as np, lightgbm as lgb
from pathlib import Path
from datetime import date as dt_date

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feat_tushare import (
    compute_features, get_tushare_db, load_index_data,
    standardize_v6 as standardize_fn,
    N_BASE, GTJA_CODES, load_gtja_compact, get_gtja_value,
)
from core import db

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'

REG20_MODEL = MODEL_DIR / 'lgb_reg_20d_v6_fixed.txt'
REG40_MODEL = MODEL_DIR / 'lgb_reg_40d_v6_fixed.txt'
NORM_STATS_20D = MODEL_DIR / 'v6_norm_stats_20d_v6_fixed.json'
NORM_STATS_40D = MODEL_DIR / 'v6_norm_stats_40d_v6_fixed.json'

W40, W20 = 0.70, 0.30

def main():
    batch_start = None
    batch_end = None
    
    for i, a in enumerate(sys.argv):
        if a == '--batch' and i+2 < len(sys.argv):
            batch_start = int(sys.argv[i+1])
            batch_end = int(sys.argv[i+2]) if sys.argv[i+2] else None
    
    today = dt_date.today()
    today_str = today.isoformat()

    print("=" * 70)
    print("融合评分系统 v10 — 详细计时版")
    print(f"  日期：{today_str}")
    if batch_start:
        print(f"  批次：{batch_start}-{batch_end or '末尾'}")
    print("=" * 70)

    # 加载模型
    t0 = time.time()
    reg20_model = lgb.Booster(model_file=str(REG20_MODEL)) if REG20_MODEL.exists() else None
    reg40_model = lgb.Booster(model_file=str(REG40_MODEL)) if REG40_MODEL.exists() else None
    stats20 = json.load(open(NORM_STATS_20D)) if NORM_STATS_20D.exists() else {}
    stats40 = json.load(open(NORM_STATS_40D)) if NORM_STATS_40D.exists() else {}
    print(f"✅ 模型加载：{(time.time()-t0)*1000:.0f}ms")

    # 连接数据库
    t0 = time.time()
    conn_state = get_state_db()
    conn_tushare = get_tushare_db()
    print(f"✅ DB 连接：{(time.time()-t0)*1000:.0f}ms")

    # 指数数据
    t0 = time.time()
    idx_close_dict = load_index_data()
    print(f"✅ 指数数据：{(time.time()-t0)*1000:.0f}ms ({len(idx_close_dict)}交易日)")

    # GTJA
    t0 = time.time()
    gtja_lookup = load_gtja_compact()
    print(f"✅ GTJA 加载：{(time.time()-t0)*1000:.0f}ms (只在第一次)")

    # 获取股票
    t0 = time.time()
    stocks = conn_tushare.execute("""
        SELECT ts_code, name FROM stock_basic WHERE delist_date IS NULL ORDER BY ts_code
    """).fetchall()
    
    if batch_start:
        idx_start = batch_start - 1
        idx_end = batch_end if batch_end else len(stocks)
        stocks = stocks[idx_start:idx_end]
    print(f"✅ 股票列表：{(time.time()-t0)*1000:.0f}ms ({len(stocks)}只)")

    # 清空旧数据（只在全量模式）
    if not batch_start:
        # 删当日旧数据（兼容两种日期格式）
        conn_state.execute(f"DELETE FROM signal_history WHERE REPLACE(date,'-','')='{today_str.replace('-','')}'")
        print(f"✅ 清空旧数据")

    results = []
    daily_sql = """SELECT date, close, open, high, low, COALESCE(change_pct, 0), volume, amount
                   FROM stock_daily WHERE stock_code=? ORDER BY date DESC LIMIT 120"""
    
    # 计时变量
    t_query = t_feat = t_model = t_other = 0
    
    for i, (code, name) in enumerate(stocks):
        code_short = code.split('.')[0]
        
        t0 = time.time()
        rows = conn_tushare.execute(daily_sql, [code_short]).fetchall()
        t_query += time.time() - t0
        
        if not rows or len(rows) < 60:
            continue
        
        rows = rows[::-1]
        closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
        lc = closes[-1]
        
        t0 = time.time()
        feat_49d, _ = compute_49d_features(code, rows, conn_tushare, gtja_lookup, idx_close_dict)
        t_feat += time.time() - t0
        
        t0 = time.time()
        reg20_pred = reg40_pred = 0.0
        if feat_49d is not None and len(feat_49d) == 49:
            f_arr = np.nan_to_num(feat_49d.reshape(1, -1), nan=0.0)
            if reg20_model and stats20:
                try:
                    reg20_pred = float(reg20_model.predict(standardize_fn(f_arr, stats20))[0])
                except: pass
            if reg40_model and stats40:
                try:
                    reg40_pred = float(reg40_model.predict(standardize_fn(f_arr, stats40))[0])
                except: pass
        t_model += time.time() - t0
        
        reg20_score = max(0.0, min(100.0, (reg20_pred + 10) / 20 * 100))
        reg40_score = max(0.0, min(100.0, (reg40_pred + 10) / 20 * 100))
        composite = reg40_score * W40 + reg20_score * W20 if reg40_model else reg20_score
        dev120 = (lc / np.mean(closes) - 1) * 100 if len(closes) >= 120 else 0
        
        results.append({
            'code': code, 'name': name, 'composite': composite,
            'reg40_pred': reg40_pred, 'reg20_pred': reg20_pred, 'dev120': dev120,
        })
        
        t_other += time.time() - t0 - (time.time() - t0)  # approximate
        
        if (i + 1) % 1000 == 0:
            print(f"  已处理 {i+1}/{len(stocks)} 只...")

    # 输出计时
    print(f"\n⏱️  耗时统计 (每只平均):")
    print(f"  查询 K 线：{t_query/len(results)*1000:.1f}ms")
    print(f"  特征计算：{t_feat/len(results)*1000:.1f}ms")
    print(f"  模型预测：{t_model/len(results)*1000:.1f}ms")
    print(f"  其他：{t_other/len(results)*1000:.1f}ms")
    print(f"  总计：{(t_query+t_feat+t_model+t_other)/len(results)*1000:.1f}ms/只")
    print(f"  {len(results)}只股票总耗时：{(t_query+t_feat+t_model+t_other)/60:.1f}分钟")

    results.sort(key=lambda x: x['composite'], reverse=True)
    
    # 写入 DB
    if '--write-db' in sys.argv:
        print(f"\n💾 写入信号...")
        t0 = time.time()
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
            except: pass
        conn_state.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print(f"✅ 写入 {inserted}条，耗时 {(time.time()-t0)*1000:.0f}ms")

    conn_tushare.close()
    conn_state.close()
    
    print(f"\n🏆 前 20 名:")
    for i, r in enumerate(results[:20], 1):
        print(f"  {i:2d}. {r['code']} {r['name'][:8]:8s} {r['composite']:6.0f}分")


def compute_49d_features(code, rows, conn, gtja_lookup, idx_close_dict):
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
        
        return np.concatenate([feat_base, np.array(gtja_vals[:11], dtype=np.float64)]), dates_str[-1]
    except:
        return None, None


if __name__ == '__main__':
    main()
