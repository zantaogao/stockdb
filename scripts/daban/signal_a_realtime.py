"""
方案A: 盘中实时打板信号
======================
每5分钟扫描，高分标的直接写入 signal_history → intraday_exec.py 自动执行

与现有系统对接：
  - 写 signal_history (action='daban', final_score=评分)
  - intraday_exec.py 已每5分钟跑 /api/execute，自动读取信号
"""

import duckdb, json, time, sys, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))

DB_PATH = os.path.expanduser('~/.hermes/stockdb/state.db')

def connect_db():
    try:
        con = duckdb.connect(str(DB_PATH))
        return con
    except Exception:
        wal = DB_PATH + '.wal'
        if os.path.exists(wal):
            os.remove(wal)
        # 重试从备份恢复
        if not os.path.exists(DB_PATH):
            bak = DB_PATH.replace('.db', '.db.bak.local')
            if os.path.exists(bak):
                import shutil
                shutil.copy2(bak, DB_PATH)
        return duckdb.connect(str(DB_PATH))

# ── Sina 扫描器 (复用 daban_scanner.py 的逻辑) ──

def fetch_sina_batch(page=1, num=40):
    """Sina批量行情接口，按涨幅排序"""
    import urllib.request as ur
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"Market_Center.getHQNodeData?page={page}&num={num}"
           "&sort=changepercent&asc=0&node=hs_a&_fields=&listtype=0")
    req = ur.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    raw = ur.urlopen(req, timeout=4).read().decode('utf-8')
    return json.loads(raw)

def score_stock(s):
    """打板评分 (梯度评分，0-100，支持超100区分涨停强度)"""
    try:
        code = s['code']
        name = s['name']
        change_pct = float(s.get('changepercent', 0))
        current_price = float(s.get('trade', 0))
        open_price = float(s.get('open', 0))
        high_price = float(s.get('high', 0))
        amount_yuan = float(s.get('amount', 0))
        turnover_ratio = float(s.get('turnoverratio', 0) or 0)
        circ_mv_wan = float(s.get('nmc', 0) or 0)  # Sina单位:万元
        settlement = float(s.get('settlement', current_price))
    except (ValueError, TypeError):
        return 0, []

    reasons = []
    score = 0  # 从零开始，不再给基础分

    if 'ST' in name or '*' in name or 'N' in name:
        return 0, ['ST/新股']
    if code.startswith('9') or code.startswith('4'):
        return 0, ['非主板/北交所']

    # 1. 涨幅梯度 (最高+30)
    if change_pct >= 9.8:
        score += 30; reasons.append('涨停')
    elif change_pct >= 7:
        add = int((change_pct - 7) / 2.8 * 20) + 10
        score += add; reasons.append(f'涨{change_pct:.1f}%')
    elif change_pct >= 3:
        score += int(change_pct / 3 * 5); reasons.append(f'+{change_pct:.1f}%')
    else:
        return 0, []

    # 2. 开盘方式梯度 (最高+15)
    if open_price > 0 and settlement > 0:
        open_pct = (open_price - settlement) / settlement * 100
        if change_pct >= 9.8:
            # 涨停且高开：越高越好
            if open_pct > 5:
                score += 15; reasons.append('高开>5%')
            elif open_pct > 3:
                score += 12; reasons.append('高开>3%')
            elif open_pct > 1:
                score += 8
        else:
            if open_pct > 2:
                score += 5

    # 3. 换手率梯度 (最高+20) - 15-25%最佳
    if turnover_ratio > 0:
        if 15 <= turnover_ratio <= 25:
            score += 20; reasons.append(f'换手{turnover_ratio:.0f}%最佳')
        elif 10 <= turnover_ratio < 15:
            score += int(10 + (turnover_ratio - 10) * 2); reasons.append(f'换手{turnover_ratio:.0f}%')
        elif 25 < turnover_ratio <= 35:
            score += int(10 + (35 - turnover_ratio) * 2); reasons.append(f'换手{turnover_ratio:.0f}%')
        elif 35 < turnover_ratio <= 50:
            score += 5  # 换手太高扣分

    circ_mv_yi = circ_mv_wan / 10000  # 万元转亿

    # 4. 市值梯度 (最高+20) - 越小越好
    if circ_mv_yi > 0:
        if circ_mv_yi < 3:
            score += 20; reasons.append(f'微盘{circ_mv_yi:.0f}亿')
        elif circ_mv_yi < 10:
            score += int(20 - (circ_mv_yi - 3) * 2); reasons.append(f'小盘{circ_mv_yi:.0f}亿')
        elif circ_mv_yi < 50:
            score += int(10 - (circ_mv_yi - 10) * 0.2); reasons.append(f'{circ_mv_yi:.0f}亿')
        elif circ_mv_yi < 200:
            score += 5

    # 5. 成交额梯度 (最高+10)
    amount_wan = amount_yuan / 10000
    if amount_wan > 50000:
        score += 10; reasons.append(f'成交{amount_wan/10000:.1f}亿')
    elif amount_wan > 10000:
        score += int((amount_wan - 10000) / 40000 * 10)
    elif amount_wan > 3000:
        score += 3

    # 6. 盘中冲高回落扣分
    if high_price > current_price * 1.03 and change_pct >= 7:
        score -= 8; reasons.append('冲高回落')

    # 7. 时间加分：越早扫描到涨停，加分越多
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    time_val = hour * 60 + minute
    if change_pct >= 9.8:
        if time_val < 1000:  # 10点前涨停
            score += 10; reasons.append('早盘封板')
        elif time_val < 1100:  # 11点前
            score += 7
        elif 1300 <= time_val < 1400:  # 下午刚开盘
            score += 3

    return max(0, score), reasons

def run_scan_and_write():
    """扫描并写入signal_history"""
    # Sina扫前3页(120只)
    all_stocks = []
    for pg in range(1, 4):
        try:
            batch = fetch_sina_batch(pg, 40)
            if not batch: break
            all_stocks.extend(batch)
        except Exception as e:
            print(f"[Sina] 第{pg}页失败: {e}")
            break

    con = connect_db()
    now = datetime.now()
    today = now.date()
    
    # 删除今天的旧打板信号（避免重复）
    con.execute("DELETE FROM signal_history WHERE date=? AND stock_name LIKE '%[打]%' ", [today])
    con.commit()

    candidates = []
    for s in all_stocks:
        sc, reasons = score_stock(s)
        if sc >= 75:  # 只推高分的
            try:
                circ_mv_wan = float(s.get('nmc', 0) or 0)
                amount_wan = float(s.get('amount', 0)) / 10000
            except:
                continue

            candidates.append({
                'code': s['code'],
                'name': f"[打]{s['name']}",  # 标记为打板信号，避免和评分信号冲突
                'industry': '',
                'score': sc,
                'reasons': reasons,
                'circ_mv_yi': circ_mv_wan / 10000,
            })

    candidates.sort(key=lambda x: -x['score'])

    if not candidates:
        print(f"  {now.strftime('%H:%M')}: 无高分标的")
        con.close()
        return []

    # 写入 signal_history - 前10只入信号表
    for c in candidates[:10]:
        try:
            con.execute("""
                DELETE FROM signal_history WHERE date=? AND stock_code=?
            """, [today, c['code']])
            
            con.execute("""
                INSERT OR REPLACE INTO signal_history 
                    (date, stock_code, stock_name, industry, final_score)
                VALUES (?, ?, ?, '打板', ?)
            """, [today, c['code'], c['name'], float(c['score'])])
                  
        except Exception as e:
            print(f"[DB] {e}")

    con.commit()
    
    # 打印结果
    top = candidates[:5]
    for c in top:
        r_str = ' '.join(c['reasons'])
        print(f"  [{c['score']:3d}] {c['code']} {c['name']:<8} | {r_str}")

    con.close()
    return candidates

def send_qq_daban(candidates):
    """发送打板信号QQ通知"""
    if not candidates:
        return

    from scripts.daban.qq_notify import format_signal_msg, send_qq
    signals = []
    for c in candidates[:10]:
        signals.append({
            'code': c['code'],
            'name': c['name'].replace('[打]', ''),
            'score': float(c['score']),
            'change_pct': 9.8 if '涨停' in ' '.join(c.get('reasons', [])) else 7.0,
            'industry': '',
            'reasons': c.get('reasons', []),
            'scan_time': datetime.now().strftime('%H:%M'),
        })

    msg = format_signal_msg(signals)
    send_qq(msg)
    print(f"  📱 QQ通知已发送")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='方案A: 盘中打板信号')
    parser.add_argument('--watch', action='store_true', help='循环模式')
    args = parser.parse_args()

    while True:
        t0 = time.time()
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 方案A扫描...")
        candidates = run_scan_and_write()
        elapsed = time.time() - t0

        # 有高分信号就发QQ通知
        if candidates:
            send_qq_daban(candidates)

        if not args.watch:
            break
        wait = max(0, 300 - elapsed)  # 5分钟
        time.sleep(wait)