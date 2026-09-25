"""ETF全市场评分脚本：每日收盘后运行，对所有ETF评分并保存到 signals.db"""
import sys, os, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import sqlite3
from core.scoring import score_etf

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'
STATE_DB = BASE / 'signals.db'  # v2温层

def get_all_etfs():
    """获取所有股票型ETF列表"""
    conn = duckdb.connect(str(TUSHARE_DB), read_only=True)
    rows = conn.execute("""
        SELECT f.ts_code, f.name
        FROM fund_basic f
        WHERE f.fund_type = '股票型'
        ORDER BY f.ts_code
    """).fetchall()
    conn.close()
    return rows

def save_etf_scores(results):
    """保存ETF评分到 signals.db.etf_scores"""
    sdb = sqlite3.connect(str(STATE_DB), timeout=30)
    sdb.execute("PRAGMA journal_mode=WAL")
    
    sdb.execute("""
        CREATE TABLE IF NOT EXISTS etf_scores (
            ts_code TEXT PRIMARY KEY,
            name TEXT,
            score REAL,
            prediction REAL,
            scan_date TEXT,
            updated_at TEXT
        )
    """)
    
    today = time.strftime('%Y-%m-%d')
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    
    for r in results:
        sdb.execute("""
            INSERT OR REPLACE INTO etf_scores (ts_code, name, score, prediction, scan_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (r['ts_code'], r['name'], r['score'], r['prediction'], today, now))
    
    sdb.commit()
    sdb.close()
    print(f"  写入 {len(results)} 只ETF评分")

def main():
    print("=" * 50)
    print(f"ETF全市场评分: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    start = time.time()
    etfs = get_all_etfs()
    print(f"ETF总数: {len(etfs)}")
    
    results = []
    skipped = 0
    errors = 0
    
    # ⚠️ 2026-08-05 修复：原逻辑"只扫未评分过的ETF"导致 etf_scores 永不更新
    # （注释说周末全量刷新但代码没有该逻辑，cron 也只是工作日 18:30）。
    # → etf_scores.scan_date 永远停在首次评分日 → 健康检查 FAIL、etf_ic 不更新。
    # 改为：每天全量重评（数据不足<140天的新ETF自然跳过，老ETF正常刷新 scan_date）。
    to_scan = etfs
    print(f"本次需评分: {len(to_scan)} 只（2026-08-05 起每天全量重评）")
    
    for i, (ts_code, name) in enumerate(to_scan):
        try:
            r = score_etf(ts_code)
            if r:
                r['name'] = name
                r['ts_code'] = ts_code
                results.append(r)
            else:
                skipped += 1
        except Exception as e:
            errors += 1
        
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start
            print(f"  进度: {i+1}/{len(to_scan)} | 已评分: {len(results)} | 跳过: {skipped} | 错误: {errors} | {elapsed:.0f}s")
    
    # 保存
    if results:
        save_etf_scores(results)
    
    elapsed = time.time() - start
    print(f"\n完成:")
    print(f"  已评分: {len(results)} 只")
    print(f"  跳过（数据不足）: {skipped} 只")
    print(f"  错误: {errors} 只")
    print(f"  耗时: {elapsed:.0f}s")

if __name__ == '__main__':
    main()
