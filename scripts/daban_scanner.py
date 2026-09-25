"""
打板扫描仪 v4 (TDX为主 + Sina备用)
===================================
盘中每5分钟扫一次，找接近涨停的强势股。

回测结论 (tushare.db, 2025.6-):
  - 首板次日均值+1.42%, 胜率55% → 利润薄，需精确执行
  - 快板(高开>3%+涨停): 连板率25.7%, T+1均值+2.60%, 胜率63.4% vs 慢板12%/+1.04%/53.7%
  - >200亿市值: 连板率45%, T+1均值+5.88% (大盘股反而收益最高!)
  - 10~50亿市值: 连板率31.8% (中盘最佳平衡)
  - 换手10-20%最佳: 连板率45.6%, T+1均值+5.89%

API通道优先级: TDX (快,~40ms) > Sina (~500ms/批) > DB兜底

用法:
  python3 scripts/daban_scanner.py          # 单次扫描
  python3 scripts/daban_scanner.py --watch   # 每5分钟循环 (盘中用)
"""

import sys, os, json, urllib.request, time
from datetime import datetime

# ── TDX通道 (首选，最快) ────────────────────────────────────

_TDX_SERVERS = [
    ('180.153.18.172', 80),
    ('106.120.54.81', 7709),
    ('60.191.117.167', 7709),
    ('180.153.18.170', 80),
]

def connect_tdx():
    """连接TDX服务器"""
    from pytdx.hq import TdxHq_API
    api = TdxHq_API(heartbeat=False)
    for ip, port in _TDX_SERVERS:
        try:
            api.connect(ip, port, time_out=3)
            return api
        except Exception:
            continue
    return None

def tdx_fetch_batch(codes_list):
    """TDX批量获取行情"""
    data = codes[0].get_security_quotes(codes_list)
    if not data:
        return []
    
    result = []
    for d in data:
        try:
            price = float(d['price'])
            prev = float(d['last_close'])
            if price > 0 and prev > 0:
                pct = round((price / prev - 1) * 100, 2)
                result.append({
                    'code': d['code'],
                    'name': '',
                    'trade': price,
                    'open': float(d.get('open', price)),
                    'high': float(d.get('high', price)),
                    'low': float(d.get('low', price)),
                    'settlement': prev,
                    'changepercent': pct,
                    'turnoverratio': 0,    # TDX不直接给换手率
                    'amount': d.get('volume', 0) * price / 100,  # 估算
                    'nmc': 0,              # 需要查市值
                })
        except (ValueError, TypeError):
            continue
    
    return result

# ── Sina通道 (备用) ────────────────────────────────────────

def fetch_sina_batch(page=1, num=40):
    """Sina批量行情接口，按涨幅排序"""
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"Market_Center.getHQNodeData?page={page}&num={num}"
           f"&sort=changepercent&asc=0&node=hs_a&_fields=&listtype=0")
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    raw = urllib.request.urlopen(req, timeout=4).read().decode('utf-8')
    return json.loads(raw)

# ── 时间判断 ────────────────────────────────────────────────

def now_dt():
    return datetime.now()

def is_trading_hours():
    t = now_dt().time()
    morning = (datetime.strptime('09:30', '%H:%M').time() <= t < datetime.strptime('11:30', '%H:%M').time())
    afternoon = (datetime.strptime('13:00', '%H:%M').time() <= t < datetime.strptime('15:00', '%H:%M').time())
    return morning or afternoon

def is_post_market():
    return now_dt().hour >= 15

# ── 打分引擎 ────────────────────────────────────────────────

def score_stock(s, mode='intraday'):
    """
    给一只股票打分 (0-100)
    
    Returns: (score, reasons_list)
    """
    try:
        code = s['code']
        name = s['name']
        change_pct = float(s.get('changepercent', 0))
        current_price = float(s.get('trade', 0))
        open_price = float(s.get('open', 0))
        high_price = float(s.get('high', 0))
        amount_yuan = float(s.get('amount', 0))
        turnover_ratio = float(s.get('turnoverratio', 0) or 0)
        circ_mv_yi = float(s.get('nmc', 0) or 0)
        settlement = float(s.get('settlement', current_price))
    except (ValueError, TypeError):
        return 0, []
    
    reasons = []
    score = 40  # 下调基础分: 首板次日均值仅+1.42%, 50太高了
    
    # ── 过滤: ST/北交所/新股 ──
    if 'ST' in name or '*' in name or 'N' in name:
        return 0, ['ST/新股']
    if code.startswith('9') or code.startswith('4'):
        return 0, ['非主板/北交所']
    
    # ── 1. 涨幅 (最高+25) ──
    if mode == 'intraday':
        if change_pct >= 9.8:
            score += 25; reasons.append('涨停')
        elif change_pct >= 7:
            add = int((change_pct - 7) / 2.8 * 15) + 10
            score += add; reasons.append(f'涨{change_pct:.1f}%')
        else:
            return 0, []
    else:
        if change_pct >= 9.8:
            score += 25; reasons.append('涨停')
        elif change_pct >= 3:
            score += int(change_pct / 10 * 15); reasons.append(f'+{change_pct:.1f}%')
    
    # ── 2. 开盘方式 (快板加分, +20) ──回测: 快板连板率25.7% vs 慢板12%, T+1均值+2.6% vs +1.04%
    if open_price > 0 and settlement > 0:
        open_pct = (open_price - settlement) / settlement * 100
        if change_pct >= 9.8 and open_pct > 3:
            score += 20; reasons.append('高开快板')  # +5→+20, 快板优势翻倍
        elif open_pct > 1:
            score += 8
        elif open_pct <= -2:
            score -= 5  # 低开封板质量差
    
    # ── 3. 换手率 (10-20%最佳, +20) ──回测: 10-20%连板率45.6%, T+1均值+5.89%
    if turnover_ratio > 0 and 10 <= turnover_ratio <= 20:
        score += 20; reasons.append(f'换手{turnover_ratio:.0f}%')
    elif turnover_ratio > 0 and 20 < turnover_ratio <= 35:
        score += 12  # 20-35%还可以, 但不如10-20%
    
    # ── 4. 市值 (大盘/中盘优先) ──回测: >200亿T+1均值+5.88%, 10~50亿连板率31.8%(最佳平衡), <3亿虽然高但样本太少
    if circ_mv_yi > 0:
        if 10 <= circ_mv_yi < 50:
            score += 20; reasons.append(f'中盘{circ_mv_yi:.0f}亿(最佳)')
        elif circ_mv_yi >= 200:
            score += 15; reasons.append(f'大盘{circ_mv_yi:.0f}亿')
        elif 50 <= circ_mv_yi < 200:
            score += 8
        elif circ_mv_yi < 3:
            score += 12; reasons.append(f'微盘{circ_mv_yi:.2f}亿(高波动)')
        # 3~10亿最差, 不加也不减
    
    # ── 5. 成交额 (流动性, +10) ──
    amount_wan = amount_yuan / 10000
    if amount_wan > 30000:
        score += 10; reasons.append(f'成交{amount_wan/10000:.1f}亿')
    elif amount_wan > 5000:
        score += 5
    
    # ── 6. 盘中冲高回落检测 ──
    if mode == 'intraday' and high_price > current_price * 1.03 and change_pct >= 7:
        score -= 8; reasons.append('冲高回落')
    
    return max(0, min(100, score)), reasons

# ── 扫描入口 (TDX优先) ──────────────────────────────────────

def scan_tdx(mode='intraday'):
    """TDX通道: 先拉全市场，筛涨幅>5%的"""
    api = connect_tdx()
    if not api:
        return []
    
    try:
        # 获取A股列表 (分沪/深)
        sh_count = api.get_security_count(1)
        sz_count = api.get_security_count(0)
        
        # 批量获取行情 (一次最多~200只，分批)
        all_quotes = []
        for market in [0, 1]:
            count = sz_count if market == 0 else sh_count
            
            for start in range(0, count, 200):
                batch_codes = [(market, f'{str(i).zfill(6)}') for i in range(start + 1, min(start + 200, count) + 1)]
                
                data = api.get_security_quotes(batch_codes)
                if data:
                    all_quotes.extend(data)
        
        # 筛选涨幅>5%的 (盘中) 或 >3%的 (盘后)
        threshold = 7.0 if mode == 'intraday' else 9.5
        
        candidates_raw = []
        for d in all_quotes:
            try:
                price = float(d['price'])
                prev = float(d['last_close'])
                if prev > 0 and price > 0:
                    pct = (price / prev - 1) * 100
                    if pct >= threshold:
                        candidates_raw.append({
                            'code': d['code'],
                            'name': '',
                            'trade': price,
                            'open': float(d.get('open', price)),
                            'high': float(d.get('high', price)),
                            'low': float(d.get('low', price)),
                            'settlement': prev,
                            'changepercent': round(pct, 2),
                            'turnoverratio': 0,    # TDX不给换手率，需要DB补
                            'amount': d.get('volume', 0) * price / 100,
                            'nmc': 0,              # TDX不给市值，需要DB补
                        })
            except (ValueError, TypeError):
                continue
        
        return candidates_raw
    
    finally:
        api.disconnect()

def scan_sina(mode='intraday'):
    """Sina通道: 按涨幅排序拉前N页"""
    pages = 3 if mode == 'intraday' else 6
    all_data = []
    
    for pg in range(1, pages + 1):
        try:
            batch = fetch_sina_batch(pg, 40)
            if not batch:
                break
            # Sina的nmc单位是万元，转成亿
            for d in batch:
                try:
                    d['nmc'] = float(d.get('nmc', 0)) / 10000
                except (ValueError, TypeError):
                    pass
            all_data.extend(batch)
        except urllib.error.HTTPError as e:
            print(f"[Sina] HTTP {e.code}，停止")
            break
        except Exception as e:
            print(f"[Sina] 失败: {e}")
            break
    
    return all_data

# ── 市值/换手率补充 (从DB读) ────────────────────────────────

def enrich_from_db(candidates):
    """用本地数据库补市值和换手率数据"""
    try:
        import duckdb
        db_path = os.path.expanduser('~/.hermes/stockdb/tushare.db')
        
        # 尝试只读连接
        conn = duckdb.connect(str(db_path), read_only=True)
        
        codes = [c['code'] for c in candidates]
        if not codes:
            return candidates
        
        ts_codes = []
        code_map = {}
        for c in codes:
            if c.startswith(('6', '9')):
                ts = f'{c}.SH'
            else:
                ts = f"{c}.SZ"
            ts_codes.append(ts)
            code_map[ts] = c['code']
        
        # 查最新daily_basic补市值+换手率
        latest_date = conn.execute("SELECT MAX(trade_date) FROM daily_basic").fetchone()[0]
        
        rows = conn.execute("""
            SELECT ts_code, circ_mv, turnover_rate_f
            FROM daily_basic WHERE trade_date = ? AND ts_code IN (""" + ','.join(['?' for _ in ts_codes]) + """)
        """, [latest_date] + ts_codes).fetchall()
        
        db_info = {r[0]: {'circ_mv': r[1], 'turnover': r[2]} for r in rows}
        
        for c in candidates:
            key = f"{c['code']}.{'SH' if c['code'].startswith(('6','9')) else 'SZ'}"
            if key in db_info:
                info = db_info[key]
                c['nmc'] = float(info['circ_mv']) / 10000 if info['circ_mv'] else 0  # 万元→亿
                c['turnoverratio'] = float(info['turnover']) if info['turnover'] else 0
        
        conn.close()
    except Exception as e:
        print(f"[DB] 补充数据失败: {e}")
    
    return candidates

# ── 输出 ────────────────────────────────────────────────────

def print_result(candidates, mode='intraday'):
    now = now_dt()
    label = "盘中打板扫描" if mode == 'intraday' else "盘后涨停复盘"
    
    print(f"\n{'='*72}")
    print(f" 打板扫描仪 | {now.strftime('%Y-%m-%d %H:%M')} | {label}")
    print(f" {'='*72}")
    
    if not candidates:
        print("  暂无符合条件标的")
        return
    
    high = [c for c in candidates if c['score'] >= 80]
    mid = [c for c in candidates if 60 <= c['score'] < 80]
    
    def show_group(title, items):
        if not items: return
        print(f"\n{title} ({len(items)}只):")
        hdr = f" {'代码':>8} {'名称':<5} {'现价':>7} {'涨幅':>5} " \
              f"{'换手%':>4} {'市值亿':>6} {'成交额万':>7} {'分':>3}"
        print(hdr)
        print("─" * 68)
        
        for c in items:
            mv = max(c['circ_mv'], 0.1)
            amt = max(c['amount_wan'], 1)
            
            line = (f" {c['code']:>8} {c['name']:<5} "
                    f"{c['price']:>7.2f} "
                    f"+{c['change_pct']:>4.1f}% "
                    f"{c.get('turnover', 0):>3.0f}% "
                    f"{mv:>6.0f}亿 "
                    f"{amt:,.0f}万 "
                    f"{c['score']:>3}")
            print(line)
            
            reasons_str = ' '.join(c.get('reasons', []))
            if reasons_str:
                print(f"         │ {reasons_str}")
    
    if high:
        show_group("★★★ 高评分 (>=80)", high)
    if mid:
        show_group("★ 中评分 (60-79)", mid[:15])

# ── 主函数 ────────────────────────────────────────────────

def run_scan():
    mode = 'intraday' if is_trading_hours() else 'review'
    
    # TDX优先，失败fallback到Sina
    candidates_raw = []
    
    try:
        start_tdx = time.time()
        tdx_data = scan_tdx(mode)
        elapsed_tdx = time.time() - start_tdx
        print(f"[TDX] 扫描{len(tdx_data)}只候选, 耗时{elapsed_tdx:.1f}s")
        
        if tdx_data:
            candidates_raw = tdx_data
    except Exception as e:
        print(f"[TDX] 失败: {e}，切换Sina...")
    
    if not candidates_raw:
        start_sina = time.time()
        sina_data = scan_sina(mode)
        elapsed_sina = time.time() - start_sina
        print(f"[Sina] 扫描{len(sina_data)}只候选, 耗时{elapsed_sina:.1f}s")
        candidates_raw = sina_data
    
    if not candidates_raw:
        print("无数据，等待开盘...")
        return []
    
    # DB补充市值/换手率
    enriched = enrich_from_db(candidates_raw)
    
    # 打分筛选
    candidates = []
    for s in enriched:
        sc, reasons = score_stock(s, mode)
        if sc > 50:
            try:
                circ_mv_yi = float(s.get('nmc', 0))
                amount_wan = float(s.get('amount', 0)) / 10000
            except:
                continue
            
            candidates.append({
                'code': s['code'],
                'name': s.get('name', ''),
                'price': float(s.get('trade', 0)),
                'change_pct': float(s.get('changepercent', 0)),
                'turnover': float(s.get('turnoverratio', 0) or 0),
                'circ_mv': circ_mv_yi,
                'amount_wan': amount_wan,
                'score': sc,
                'reasons': reasons,
            })
    
    candidates.sort(key=lambda x: -x['score'])
    print_result(candidates, mode)
    return candidates

def main():
    import argparse
    parser = argparse.ArgumentParser(description='打板扫描仪')
    parser.add_argument('--watch', action='store_true', help='循环模式 (每5分钟)')
    parser.add_argument('--interval', type=int, default=300, help='间隔秒数(默认300)')
    args = parser.parse_args()
    
    while True:
        t0 = time.time()
        run_scan()
        elapsed = time.time() - t0
        print(f"\n 耗时 {elapsed:.1f}s")
        
        if not args.watch:
            break
        
        wait = max(0, args.interval - elapsed)
        time.sleep(wait)

if __name__ == '__main__':
    main()
