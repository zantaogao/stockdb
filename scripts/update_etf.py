#!/usr/bin/env python3
"""独立 ETF 数据更新脚本 — 拉取 fund_basic + fund_daily"""
import sys, json, time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import duckdb
import tushare as ts
from core.db import TUSHARE_DB_PATH
from core.db_lock import start_hard_watchdog

start_hard_watchdog(25, label='update_etf')  # 2026-09-01 防霸锁

def main():
    # 写锁：与主更新互斥，防止 os.replace 冲突
    from core.db_lock import tushare_write_lock
    with tushare_write_lock(timeout=600):
        print("=" * 50)
        print("ETF 数据更新（受写锁保护）")
        print("=" * 50)
        
        pro = ts.pro_api()
        
        # 建表
        conn = duckdb.connect(str(TUSHARE_DB_PATH))
        conn.execute("CREATE TABLE IF NOT EXISTS fund_basic (ts_code VARCHAR PRIMARY KEY, name VARCHAR, fund_type VARCHAR, list_date VARCHAR, found_date VARCHAR, market VARCHAR, invest_type VARCHAR)")
        conn.execute("CREATE TABLE IF NOT EXISTS fund_daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE, PRIMARY KEY (ts_code, trade_date))")
        conn.close()
        
        db = duckdb.connect(str(TUSHARE_DB_PATH))
        
        # 1. ETF 列表
        print("\n=== fund_basic (ETF 列表) ===")
        df = pro.fund_basic(market='E')
        if df is not None and len(df) > 0:
            keep = [c for c in ['ts_code','name','fund_type','list_date','found_date','market','invest_type'] if c in df.columns]
            db.execute("DELETE FROM fund_basic")
            for _, row in df[keep].iterrows():
                db.execute("INSERT INTO fund_basic VALUES (?,?,?,?,?,?,?)",
                           (row['ts_code'], row.get('name',''), row.get('fund_type',''),
                            str(row.get('list_date','') or ''), str(row.get('found_date','') or ''),
                            row.get('market',''), row.get('invest_type','')))
            print(f"  ETF 总数: {len(df)}")
        else:
            print("  无数据")
        
        # 2. ETF 净值
        # 2026-08-27 修复: 按"已有历史优先"排序(158/159 新ETF 无数据全排在前面导致前1600只全空转);
        # 非 limit 异常打印(原静默吞掉难排查)
        codes = [r[0] for r in db.execute("SELECT ts_code FROM fund_basic WHERE list_date IS NOT NULL AND list_date != ''").fetchall()]
        has_hist = set(r[0] for r in db.execute("SELECT DISTINCT ts_code FROM fund_daily").fetchall())
        codes = sorted(codes, key=lambda c: (c not in has_hist, c))  # 有历史优先
        print(f"\n=== fund_daily (ETF 净值) ===")
        print(f"  待处理: {len(codes)} 只 (有历史 {len(codes) - sum(1 for c in codes if c not in has_hist)} 只优先)")

        total = 0
        n_no_data = 0
        import time as _t
        for i, c in enumerate(codes):
            try:
                latest = db.execute("SELECT MAX(trade_date) FROM fund_daily WHERE ts_code=?", [c]).fetchone()[0]
                # 2026-09-01 修复: str(int+1) 月末产出 20260832 非法日期, 改日历递增
                start = ((datetime.strptime(str(latest).replace('-',''), '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')) if latest else '20250101'
                end = datetime.now().strftime('%Y%m%d')
                if start > end:
                    continue

                df2 = pro.fund_daily(ts_code=c, start_date=start, end_date=end)
                if df2 is not None and len(df2) > 0:
                    db.execute("DELETE FROM fund_daily WHERE ts_code=? AND trade_date>=?", (c, start))
                    written = 0
                    for _, row in df2.iterrows():
                        db.execute("INSERT OR REPLACE INTO fund_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (row['ts_code'], str(row['trade_date']),
                             float(row.get('open',0)), float(row.get('high',0)),
                             float(row.get('low',0)), float(row.get('close',0)),
                             float(row.get('pre_close',0)), float(row.get('change',0)),
                             float(row.get('pct_chg',0)), float(row.get('vol',0)),
                             float(row.get('amount',0))))
                        written += 1
                    total += written
                elif not latest:
                    n_no_data += 1  # 无历史且接口无数据(未上市/无净值), 后续不再重复拉
            except Exception as e:
                # 限流判断: 中英文都覆盖(原 'limit' 匹配不上"频率超限"→静默跳过的坑, 2026-08-27)
                if 'limit' in str(e).lower() or '频率' in str(e) or '频次' in str(e):
                    print("  API 限流，等待 65s...", flush=True)
                    time.sleep(65)
                else:
                    print(f"  ⚠️ {c} 异常: {str(e)[:100]}", flush=True)

            _t.sleep(0.15)  # 频率控制: fund_daily 500次/分钟上限, 0.15s/只 ≈ 400次/分钟 安全

            if (i+1) % 100 == 0:
                print(f"  {i+1}/{len(codes)}, +{total} 条 (无数据新ETF {n_no_data} 只)", flush=True)
        
        db.execute("CHECKPOINT")
        db.close()
        print(f"\n✅ ETF 更新完成: fund_daily +{total} 条")

if __name__ == '__main__':
    main()
