"""
方案B: 盘前预判入池 + 盘中确认
===============================
9:00 预扫描，找昨天涨停的票入"打板观察池"。
盘中每5分钟检查池中股票状态：接近涨停时推信号。

逻辑（基于回测结论）：
  - 昨天涨停的股 → 今天高开>3%冲板 = 连板候选
  - 同行业有涨停集群 → 加分
"""

import duckdb, json, time, sys, os, sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.expanduser('~/.hermes/stockdb/ledger.db')  # v2热层(注: 本工具daily/stk_limit查询原state.db即无此表,疑似早已失效)
SIGNALS_DB = os.path.expanduser('~/.hermes/stockdb/signals.db')  # v2温层: signal_history


def connect_db(read_only=True):
    try:
        con = duckdb.connect(str(DB_PATH), read_only=read_only)
        con.execute("ATTACH IF NOT EXISTS '~/.hermes/stockdb/tushare.db' AS ts (READ_ONLY)")
        return con
    except Exception:
        wal = DB_PATH + '.wal'
        if os.path.exists(wal):
            os.remove(wal)
        con = duckdb.connect(str(DB_PATH), read_only=read_only)
        con.execute("ATTACH IF NOT EXISTS '~/.hermes/stockdb/tushare.db' AS ts (READ_ONLY)")
        return con


def premarket_scan():
    """9:00运行，找昨天涨停的票入观察池"""
    today = datetime.now().date()
    con = connect_db()

    # 最新交易日
    yesterday = con.execute("""
        SELECT DISTINCT trade_date FROM stk_limit 
        ORDER BY CAST(trade_date AS INTEGER) DESC LIMIT 1
    """).fetchone()[0]

    print(f"\n=== 盘前预判 | {today} ===")
    print(f"参考昨日: {yesterday}")

    # 分步查：先找涨停代码，再批量补info（避免大JOIN超时）
    limit_codes = con.execute("""
        SELECT d.ts_code, d.close as limit_price, d.pct_chg, d.pre_close
        FROM ts.daily d
        INNER JOIN ts.stk_limit sl ON d.ts_code = sl.ts_code AND sl.trade_date = ?
        WHERE d.trade_date = ? AND d.close >= sl.up_limit * 0.98
    """, [yesterday, yesterday]).fetchall()

    print(f"昨日涨停: {len(limit_codes)}只")

    if not limit_codes:
        con.close()
        return []

    # 提取短代码(去掉.SZ/.SH)
    short_codes = list(set([r[0][:6] for r in limit_codes]))

    # 批量查 stock_info
    info_rows = con.execute("""
        SELECT stock_code, stock_name, industry FROM stock_info 
        WHERE stock_code IN ?
    """, [short_codes]).fetchall()

    info_map = {r[0]: (r[1], r[2]) for r in info_rows}

    # 批量查 daily_basic
    basic_rows = con.execute("""
        SELECT ts_code, circ_mv, turnover_rate_f FROM daily_basic 
        WHERE trade_date = ? AND ts_code IN ?
    """, [yesterday, [r[0] for r in limit_codes]]).fetchall()

    basic_map = {r[0]: (r[1], r[2]) for r in basic_rows}

    # 构建观察池，过滤掉ST和大市值
    pool = []
    for ts_code, price, pct_chg, pre_close in limit_codes:
        code6 = ts_code[:6]
        stock_name, industry = info_map.get(code6, (None, None))

        if not stock_name or 'ST' in str(stock_name) or '*' in str(stock_name):
            continue

        # circ_mv 单位是万元
        circ_mv, turnover = basic_map.get(ts_code, (0, 0))
        circ_mv_yi = round(circ_mv / 1e4, 0) if circ_mv else None  # 万元→亿元

        if circ_mv and circ_mv > 50e4:  # >50亿 (50e4 万元)
            continue

        pool.append({
            'ts_code': ts_code,
            'stock_name': stock_name,
            'industry': industry or '',
            'limit_price': price,
            'pct_chg': pct_chg,
            'circ_mv_yi': circ_mv_yi,
            'turnover': round(turnover, 1) if turnover else None,
        })

    # 按涨幅排序，取前200
    pool.sort(key=lambda x: -x['pct_chg'])
    pool = pool[:200]

    print(f"观察池: {len(pool)}只（过滤ST+大市值后）")

    if not pool:
        con.close()
        return []

    # 写入观察池表
    con.close()  # Close read connection first
    try:
        write_con = connect_db(read_only=False)
        today_str = str(today)

        write_con.execute("""
            CREATE TABLE IF NOT EXISTS daban_watch_pool (
                scan_date DATE, stock_code VARCHAR, stock_name VARCHAR, 
                industry VARCHAR, limit_price DOUBLE, pct_chg DOUBLE,
                circ_mv_yi DOUBLE, turnover DOUBLE, open_type VARCHAR,
                signal_sent BOOLEAN DEFAULT FALSE
            )
        """)

        write_con.execute("DELETE FROM daban_watch_pool WHERE scan_date=?", [today_str])

        for row in pool:
            try:
                write_con.execute("""
                    INSERT INTO daban_watch_pool 
                        (scan_date, stock_code, stock_name, industry, limit_price, pct_chg, circ_mv_yi, turnover, open_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [today_str, row['ts_code'], row['stock_name'], row['industry'],
                      row['limit_price'], row['pct_chg'], row.get('circ_mv_yi', 0), 
                      row.get('turnover', 0), 'fast' if abs(row['pct_chg']) >= 20 else 'normal'])
            except Exception:
                pass

        write_con.commit()
    except Exception as e:
        print(f"[DB] {e}")

    # 打印Top10
    print("\n前10只:")
    for row in pool[:10]:
        mv = f"{row['circ_mv_yi']:.0f}" if row.get('circ_mv_yi') else 'N/A'
        tr = f"{row['turnover']}%" if row.get('turnover') else 'N/A'
        print(f"  {row['ts_code']} {row['stock_name']:<8} {row['industry']:<6} "
              f"涨停价{row['limit_price']:.2f} +{row['pct_chg']:.1f}% "
              f"市值{mv}亿 换手{tr}")

    con.close()
    return pool


def intraday_confirm():
    """每5分钟跑，检查池中股票是否接近涨停"""
    import urllib.request as ur

    today = datetime.now().date()

    con = connect_db()
    rows = con.execute("""
        SELECT stock_code, stock_name, industry, limit_price, pct_chg, circ_mv_yi, turnover
        FROM daban_watch_pool WHERE scan_date=? AND signal_sent IS NOT TRUE
    """, [str(today)]).fetchall()

    if not rows:
        print(f"  {datetime.now().strftime('%H:%M')}: 观察池为空")
        con.close()
        return []

    pool_info = {r[0]: r for r in rows}

    # Sina实时查询
    signals = []

    try:
        def code_to_sina(c):
            """Convert stock_code to Sina API format."""
            clean = c.replace('.SH','').replace('.SZ','').replace('.BJ','')
            if c.endswith('.BJ'): return f'bj{clean}'
            elif c.startswith('6'): return f'sh{clean}'
            else: return f'sz{clean}'

        sina_list = ','.join([code_to_sina(c) for c, *_ in rows])

        url = f"https://hq.sinajs.cn/list={sina_list}"
        req = ur.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        raw = ur.urlopen(req, timeout=3).read().decode('gbk')

        for line in raw.strip().split('\n'):
            if '=""' in line or 'hq_str_' not in line:
                continue

            parts = line.split('"')[1].split(',')
            scode = line.split('=')[0].replace('var hq_str_', '')
            code_clean = scode[2:]

            ts_code = f'{code_clean}.BJ' if code_clean.startswith('92') else (f'{code_clean}.SH' if code_clean.startswith(('6', '9')) else f'{code_clean}.SZ')

            current_price = float(parts[3])
            prev_close = float(parts[2])
            change_pct = (current_price - prev_close) / prev_close * 100

            if ts_code not in pool_info or change_pct < 5:
                continue

            info = pool_info[ts_code]
            score = 0
            reasons = []

            # 1. 涨幅梯度 (最高+30)
            if change_pct >= 9.8:
                score += 30; reasons.append('涨停')
            elif change_pct >= 7:
                score += int(10 + (change_pct - 7) / 2.8 * 20); reasons.append(f'涨{change_pct:.1f}%')
            else:
                score += int(change_pct / 10 * 10)

            # 2. 突破昨日涨停价 (最高+15)
            open_diff = (current_price - info[3]) / info[3] * 100 if info[3] else 0
            if open_diff > 3:
                score += 15; reasons.append(f'突破昨涨停+{open_diff:.1f}%')
            elif open_diff > 1:
                score += 10; reasons.append(f'突破昨涨停+{open_diff:.1f}%')
            elif open_diff > 0.5:
                score += 5

            # 3. 换手率梯度 (最高+20) - 15-25%最佳
            turnover = info[6] if len(info) > 6 and info[6] else 0
            if turnover > 0:
                if 15 <= turnover <= 25:
                    score += 20; reasons.append(f'换手{turnover:.0f}%最佳')
                elif 10 <= turnover < 15:
                    score += int(10 + (turnover - 10) * 2); reasons.append(f'换手{turnover:.0f}%')
                elif 25 < turnover <= 35:
                    score += int(10 + (35 - turnover) * 2); reasons.append(f'换手{turnover:.0f}%')
                elif 35 < turnover <= 50:
                    score += 5

            # 4. 市值梯度 (最高+20) - 越小越好
            mv_yi = info[5] if len(info) > 5 else 0
            if mv_yi and mv_yi > 0:
                if mv_yi < 3:
                    score += 20; reasons.append(f'微盘{mv_yi:.0f}亿')
                elif mv_yi < 10:
                    score += int(20 - (mv_yi - 3) * 2); reasons.append(f'小盘{mv_yi:.0f}亿')
                elif mv_yi < 50:
                    score += int(10 - (mv_yi - 10) * 0.2); reasons.append(f'{mv_yi:.0f}亿')
                elif mv_yi < 200:
                    score += 5

            # 5. 时间加分
            now = datetime.now()
            time_val = now.hour * 60 + now.minute
            if change_pct >= 9.8:
                if time_val < 1000:
                    score += 10; reasons.append('早盘封板')
                elif time_val < 1100:
                    score += 7
                elif 1300 <= time_val < 1400:
                    score += 3

            if score >= 60:
                signals.append({
                    'code': ts_code,
                    'name': info[1],
                    'industry': info[2] or '',
                    'score': min(100, score),
                    'change_pct': round(change_pct, 1),
                    'price': current_price,
                    'reasons': reasons,
                })

    except Exception as e:
        print(f"[Sina] {e}")

    if signals:
        con.close()
        write_con = connect_db(read_only=False)

        for s in sorted(signals, key=lambda x: -x['score'])[:8]:
            try:
                sig_con = sqlite3.connect(SIGNALS_DB, timeout=30); sig_con.execute("PRAGMA busy_timeout=5000")
                sig_con.execute("DELETE FROM signal_history WHERE date=? AND stock_code=?", 
                                  [today, s['code']])
                sig_con.execute("""
                    INSERT OR REPLACE INTO signal_history (date, stock_code, stock_name, final_score)
                    VALUES (?, ?, '打板-B [池]', ?)""",
                    [today, s["code"], s["name"], float(s['score'])])
                sig_con.commit()

                write_con.execute("UPDATE daban_watch_pool SET signal_sent = TRUE "
                                  "WHERE scan_date=? AND stock_code=?", 
                                  [str(today), s['code']])
            except Exception:
                pass

        write_con.commit()

        print(f"\n  [{datetime.now().strftime('%H:%M')}] 方案B确认信号:")
        for s in signals[:5]:
            r_str = ' '.join(s['reasons'])
            print(f"    [{s['score']:3d}] {s['code']} {s['name']:<8} +{s['change_pct']}% | {r_str}")

    con.close()
    return signals


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='方案B: 盘前预判+盘中确认')
    parser.add_argument('--premarket', action='store_true', help='盘前预扫描(9:00)')
    parser.add_argument('--confirm', action='store_true', help='盘中确认单次')
    parser.add_argument('--watch', action='store_true', help='盘中循环模式')

    args = parser.parse_args()

    if args.premarket or (not args.confirm and not args.watch):
        print("\n=== 方案B: 盘前预判 ===")
        premarket_scan()

    if args.confirm or args.watch:
        while True:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 方案B盘中确认...")
            intraday_confirm()
            if not args.watch:
                break
            time.sleep(300)
