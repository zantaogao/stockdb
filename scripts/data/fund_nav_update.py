#!/usr/bin/env python3
"""
基金净值增量更新 v3 — 跳过无效基金代码
- 只更新近7天无净值、但历史有过数据的基金
- 每批最多500只
"""
import akshare as ak
import duckdb
import json, sys, time, random
from pathlib import Path
from datetime import date, timedelta

DB_DIR = Path.home() / '.hermes' / 'stockdb'
DB_PATH = DB_DIR / 'fund.db'
SLEEP = 0.6
MAX_PER_RUN = 500
# 已知不存在的代码（历史失败过，跳过）
SKIP_CODES = set()


def get_funds_to_update(conn):
    today = date.today().isoformat()
    seven_days_ago = (date.today() - timedelta(days=7)).isoformat()

    rows = conn.execute(f"""
        SELECT f.fund_code
        FROM fund_info f
        LEFT JOIN (
            SELECT fund_code, MAX(date) as last_date
            FROM fund_nav_daily
            GROUP BY fund_code
        ) n ON f.fund_code = n.fund_code
        WHERE n.last_date IS NOT NULL 
          AND n.last_date < '{seven_days_ago}'
          AND f.fund_code NOT IN (
            SELECT fund_code FROM fund_nav_daily 
            WHERE date = '{today}'
          )
        ORDER BY n.last_date ASC, f.fund_code
        LIMIT {MAX_PER_RUN}
    """).fetchall()
    return [r[0] for r in rows if r[0] not in SKIP_CODES]


def fetch_nav(code):
    for attempt in range(2):
        try:
            df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
            if df is not None and not df.empty:
                import pandas as pd
                df['净值日期'] = pd.to_datetime(df['净值日期']).dt.date
                start = date.today() - timedelta(days=30)
                df = df[df['净值日期'] >= start]
                return df, None
            return None, "空数据"
        except Exception as e:
            err = str(e)
            if 'Unexpected token' in err or 'Data_netWorthTrend' in err:
                time.sleep(3)
                continue
            return None, err[:60]
    return None, "API无效"


def main():
    sys.stdout.reconfigure(line_buffering=True)
    print(f"基金净值更新 — {date.today()}")

    if not DB_PATH.exists():
        print("❌ fund.db 不存在"); return

    conn = duckdb.connect(str(DB_PATH))
    to_update = get_funds_to_update(conn)
    print(f"需更新: {len(to_update)} 只（限{MAX_PER_RUN}只/批）")

    if not to_update:
        print("✅ 全部已是最新")
        conn.close(); return

    success = fail = 0
    for i, code in enumerate(to_update):
        print(f"  [{i+1}/{len(to_update)}] {code}...", end=" ", flush=True)

        df, err = fetch_nav(code)
        if err:
            print(f"✗ {err}")
            fail += 1
            SKIP_CODES.add(code)
        else:
            rows = []
            for _, row in df.iterrows():
                try:
                    dt = str(row.get('净值日期', ''))[:10]
                    if dt == 'None' or dt == 'NaT': continue
                    unit_nav = float(row.get('单位净值', 0))
                    if unit_nav <= 0: continue
                    chg = float(row.get('日增长率', 0)) or 0.0
                    rows.append(code)
                    conn.execute(
                        f"""INSERT OR REPLACE INTO fund_nav_daily 
                           (fund_code, date, unit_nav, accum_nav, adj_nav, change_pct)
                           VALUES ('{code}', '{dt}', {unit_nav}, {unit_nav}, {unit_nav}, {chg})"""
                    )
                except: continue
            conn.commit()
            print(f"✅ +{len(rows)}条")
            success += 1

        time.sleep(SLEEP + random.uniform(0, 0.15))

    today_cnt = conn.execute(
        f"SELECT COUNT(DISTINCT fund_code) FROM fund_nav_daily WHERE date='{date.today().isoformat()}'"
    ).fetchone()[0]
    conn.close()
    print(f"\n✅ 完成! 成功:{success} 失败:{fail}")
    print(f"今日已有净值: {today_cnt} 只基金")


if __name__ == '__main__':
    main()
