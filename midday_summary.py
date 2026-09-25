#!/usr/bin/env python3
"""Mid-day market summary - fetch real-time quotes and generate report.
Uses DuckDB for historical data & Sina for real-time quotes."""
import json, urllib.request, re, datetime, sys, os, statistics

DB_PATH = os.path.expanduser('~/.hermes/stockdb/tushare.db')
HOLDINGS_PATH = '/Users/zantao/.hermes/stockdb/holdings.json'

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

def sina_quote(codes):
    if not codes:
        return {}
    url = f"http://hq.sinajs.cn/list={','.join(codes)}"
    req = urllib.request.Request(url, headers={
        'Referer': 'http://finance.sina.com.cn',
        'User-Agent': 'Mozilla/5.0'
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gbk')
    except Exception as e:
        print(f"WARN: Sina error: {e}", file=sys.stderr)
        return {}
    result = {}
    for line in raw.strip().split('\n'):
        line = line.strip()
        if not line: continue
        m = re.search(r'var hq_str_([^=]+)="(.+)"', line)
        if not m: continue
        code = m.group(1)
        parts = m.group(2).split(',')
        if len(parts) < 32: continue
        try:
            result[code] = {
                'name': parts[0],
                'current': float(parts[3]) if parts[3] else None,
                'prev_close': float(parts[2]) if parts[2] else None,
                'high': float(parts[4]) if parts[4] else None,
                'low': float(parts[5]) if parts[5] else None,
                'volume': float(parts[8]) if parts[8] else 0,
                'amount': float(parts[9]) if parts[9] else 0,
            }
            if result[code]['current'] and result[code]['prev_close']:
                result[code]['chg_pct'] = (result[code]['current'] - result[code]['prev_close']) / result[code]['prev_close'] * 100
            else:
                result[code]['chg_pct'] = None
        except (ValueError, IndexError):
            continue
    return result

def code_to_sina(code):
    code = code.strip()
    if code.startswith(('6','9')): return f"sh{code}"
    elif code.startswith(('0','3')): return f"sz{code}"
    elif code.startswith(('4','8')): return f"bj{code}"
    return f"sh{code}"

def query_duckdb_ma(codes):
    """Query DuckDB for MA data and latest trading prices."""
    if not HAS_DUCKDB or not os.path.exists(DB_PATH):
        print("WARN: DuckDB not available or DB not found", file=sys.stderr)
        return {}, None
    
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)
        result = {}
        latest_date = None
        
        # Get latest date
        row = conn.execute("SELECT MAX(date) as d FROM stock_daily").fetchone()
        if row and row[0]:
            latest_date = str(row[0])
        
        for code in codes:
            clean = code.strip()
            # Get last 250 trading days
            rows = conn.execute("""
                SELECT date, close, volume, amount 
                FROM stock_daily 
                WHERE stock_code = ? 
                ORDER BY date DESC 
                LIMIT 250
            """, (clean,)).fetchall()
            
            if not rows or len(rows) < 20:
                result[clean] = {}
                continue
            
            closes = [r[1] for r in rows]
            dates = [str(r[0]) for r in rows]
            volumes = [r[2] or 0 for r in rows]
            
            ma5 = statistics.mean(closes[:5]) if len(closes) >= 5 else None
            ma20 = statistics.mean(closes[:20]) if len(closes) >= 20 else None
            ma60 = statistics.mean(closes[:60]) if len(closes) >= 60 else None
            ma120 = statistics.mean(closes[:120]) if len(closes) >= 120 else None
            ma250 = statistics.mean(closes[:250]) if len(closes) >= 250 else None
            
            latest_close = closes[0]
            prev_close = closes[1] if len(closes) > 1 else None
            vol_ma5 = statistics.mean(volumes[:5]) if len(volumes) >= 5 else 0
            vol_ratio = latest_close / vol_ma5 if vol_ma5 > 0 else None  # close doesn't make sense here
            # Actually compute vol ratio properly
            latest_vol = volumes[0]
            vol_ma5_val = statistics.mean(volumes[:5]) if len(volumes) >= 5 else 0
            vol_ratio = latest_vol / vol_ma5_val if vol_ma5_val > 0 else None
            
            d = {
                'close': latest_close, 'prev_close': prev_close,
                'ma5': ma5, 'ma20': ma20, 'ma60': ma60, 'ma120': ma120, 'ma250': ma250,
                'latest_date': dates[0], 'vol_ratio': vol_ratio,
            }
            if ma60 and latest_close:
                d['ma60_dev'] = (latest_close - ma60) / ma60 * 100
            if ma120 and latest_close:
                d['ma120_dev'] = (latest_close - ma120) / ma120 * 100
            if ma250 and latest_close:
                d['ma250_dev'] = (latest_close - ma250) / ma250 * 100
            
            result[clean] = d
        
        conn.close()
        return result, latest_date
    except Exception as e:
        print(f"WARN: DuckDB error: {e}", file=sys.stderr)
        return {}, None

def query_index_ma():
    """Query SH index 60-day MA from DuckDB index_daily."""
    if not HAS_DUCKDB or not os.path.exists(DB_PATH):
        return None
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)
        rows = conn.execute("""
            SELECT close FROM index_daily 
            WHERE index_code = '000001' 
            ORDER BY date DESC LIMIT 60
        """).fetchall()
        conn.close()
        if rows and len(rows) >= 60:
            closes = [r[0] for r in rows]
            ma60 = statistics.mean(closes[:60])
            latest = closes[0]
            return (latest - ma60) / ma60 * 100
        return None
    except Exception as e:
        print(f"WARN: Index MA error: {e}", file=sys.stderr)
        return None

def fmt_pct(v, suffix='%'):
    if v is None: return '--'
    return f"{v:+.2f}{suffix}"

def fmt_price(v):
    if v is None: return '--'
    return f"{v:.2f}"

def main():
    # Load holdings
    with open(HOLDINGS_PATH) as f:
        data = json.load(f)
    
    positions = data['positions']
    hold_positions = [p for p in positions if p.get('status') == 'hold']
    watch_positions = [p for p in positions if p.get('status') == 'watch_active']
    
    # Collect all stock codes
    all_codes = set()
    for p in hold_positions:
        all_codes.add(p['code'])
    for p in watch_positions:
        all_codes.add(p['code'])
    
    print(f"Data: {len(hold_positions)} hold, {len(watch_positions)} watch_active, {len(all_codes)} unique codes", file=sys.stderr)
    
    # Sina real-time quotes
    index_codes = ['sh000001', 'sz399001', 'sz399006']
    sina_targets = index_codes + [code_to_sina(c) for c in sorted(all_codes)]
    quotes = sina_quote(sina_targets)
    print(f"Sina quotes: {len(quotes)}", file=sys.stderr)
    
    # DuckDB historical data
    db_data, latest_db_date = query_duckdb_ma(list(all_codes))
    index_ma60_dev = query_index_ma()
    print(f"DB data: {len(db_data)} stocks, latest={latest_db_date}", file=sys.stderr)
    
    now = datetime.datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    
    # ========== BUILD REPORT ==========
    lines = []
    lines.append(f"📊 **午盘总结** | {date_str}")
    lines.append("")
    
    # --- 大盘 ---
    sh = quotes.get('sh000001', {})
    sz = quotes.get('sz399001', {})
    cy = quotes.get('sz399006', {})
    
    sh_price = sh.get('current')
    sh_chg = sh.get('chg_pct')
    
    sh_line = f"上证 {fmt_price(sh_price)} ({fmt_pct(sh_chg)})"
    if index_ma60_dev is not None:
        sh_line += f" | 60日线偏离 {fmt_pct(index_ma60_dev)}"
    sh_line += f" | 深证 {fmt_price(sz.get('current'))} ({fmt_pct(sz.get('chg_pct'))})"
    sh_line += f" | 创业板 {fmt_price(cy.get('current'))} ({fmt_pct(cy.get('chg_pct'))})"
    lines.append(f"**大盘：** {sh_line}")
    lines.append("")
    
    # --- 持仓 ---
    lines.append(f"**持仓（{len(hold_positions)}只）：**")
    lines.append("")
    
    enriched_hold = []
    for p in hold_positions:
        c = p['code']
        q = quotes.get(code_to_sina(c), {})
        db = db_data.get(c, {})
        
        live_price = q.get('current') or db.get('close')
        live_chg = q.get('chg_pct')
        buy_price = p.get('buy_price')
        stop_loss = p.get('stop_loss')
        
        pnl_pct = ((live_price - buy_price) / buy_price * 100) if live_price and buy_price and buy_price > 0 else None
        
        stop_dist = None
        stop_hit = False
        if live_price and stop_loss and stop_loss > 0:
            stop_dist = (live_price - stop_loss) / stop_loss * 100
            stop_hit = stop_dist <= 0
        
        long_dev = db.get('ma250_dev') or db.get('ma120_dev')
        
        enriched_hold.append({
            'code': c,
            'name': q.get('name', p.get('name', c)),
            'price': live_price, 'chg_pct': live_chg,
            'pnl_pct': pnl_pct,
            'stop_loss': stop_loss, 'stop_dist': stop_dist, 'stop_hit': stop_hit,
            'long_dev': long_dev,
            'buy_price': buy_price, 'vol_ratio': db.get('vol_ratio'),
        })
    
    enriched_hold.sort(key=lambda x: x.get('chg_pct') or 0, reverse=True)
    
    gainers = [s for s in enriched_hold if s['chg_pct'] is not None and s['chg_pct'] > 2]
    losers  = [s for s in enriched_hold if s['chg_pct'] is not None and s['chg_pct'] < -2]
    stop_warn = [s for s in enriched_hold if s['stop_dist'] is not None and s['stop_dist'] < 5 and not s['stop_hit']]
    rest = [s for s in enriched_hold if s not in gainers and s not in losers and s not in stop_warn]
    
    def fmt_hold(s):
        line = f"• {s['code']} {s['name']} {fmt_price(s['price'])} ({fmt_pct(s['chg_pct'])})"
        if s['pnl_pct'] is not None:
            line += f" | 浮盈{fmt_pct(s['pnl_pct'])}"
        if s['stop_loss']:
            line += f" | 止损 {fmt_price(s['stop_loss'])}"
            if s['stop_hit']:
                line += " 🔴已触发"
            elif s['stop_dist'] is not None:
                line += f" | 距 {fmt_pct(s['stop_dist'])}"
        if s['long_dev'] is not None:
            line += f" | 年线 {fmt_pct(s['long_dev'])}"
        return line
    
    if gainers:
        lines.append("📈 **领涨（涨幅>2%）：**")
        for s in gainers: lines.append(fmt_hold(s))
        lines.append("")
    
    if losers:
        lines.append("📉 **领跌（跌幅>2%）：**")
        for s in losers: lines.append(fmt_hold(s))
        lines.append("")
    
    if stop_warn:
        lines.append("⚠️ **止损预警：**")
        for s in stop_warn: lines.append(fmt_hold(s))
        lines.append("")
    
    if rest:
        lines.append("**其余持仓：**")
        for s in rest: lines.append(fmt_hold(s))
        lines.append("")
    
    # --- 观察名单 (watch_active) ---
    lines.append(f"**观察名单（{len(watch_positions)}只，watch_active）：**")
    lines.append("")
    
    enriched_watch = []
    for p in watch_positions:
        c = p['code']
        q = quotes.get(code_to_sina(c), {})
        db = db_data.get(c, {})
        
        live_price = q.get('current') or db.get('close')
        live_chg = q.get('chg_pct')
        stop_loss = p.get('stop_loss')
        
        stop_dist = None
        if live_price and stop_loss and stop_loss > 0:
            stop_dist = (live_price - stop_loss) / stop_loss * 100
        
        long_dev = db.get('ma250_dev') or db.get('ma120_dev')
        
        enriched_watch.append({
            'code': c, 'name': q.get('name', p.get('name', c)),
            'price': live_price, 'chg_pct': live_chg,
            'stop_loss': stop_loss, 'stop_dist': stop_dist,
            'long_dev': long_dev,
        })
    
    enriched_watch.sort(key=lambda x: x.get('chg_pct') or 0, reverse=True)
    
    for s in enriched_watch:
        marker = ""
        if s['chg_pct'] is not None:
            if s['chg_pct'] > 3: marker = " 🟢"
            elif s['chg_pct'] > 5: marker = " 🟢🟢"
            elif s['chg_pct'] < -3: marker = " 🔴"
        
        line = f"• {s['code']} {s['name']} {fmt_price(s['price'])} ({fmt_pct(s['chg_pct'])}){marker}"
        if s['stop_loss']:
            line += f" | 止损 {fmt_price(s['stop_loss'])}"
            if s['stop_dist'] is not None:
                line += f" ({fmt_pct(s['stop_dist'])})"
        if s['long_dev'] is not None:
            line += f" | 年线 {fmt_pct(s['long_dev'])}"
        lines.append(line)
    
    lines.append("")
    
    # --- 午后策略 ---
    lines.append("**午后策略：**")
    strategy = []
    
    if sh_chg is not None:
        if sh_chg > 1.5:
            strategy.append("🔴 上证涨幅>1.5%，追高风险大，观望为主")
        elif sh_chg < -1.5:
            strategy.append("🔴 上证跌幅>1.5%，盘中急跌可能，仅硬止损执行")
    
    hit_stops = [s for s in enriched_hold if s['stop_hit']]
    if hit_stops:
        strategy.append(f"⚠️ {', '.join(s['name'] for s in hit_stops)} 已止损！午后执行卖出")
    
    near_stops = [s for s in enriched_hold if s.get('stop_dist') is not None and 0 < s['stop_dist'] < 3]
    if near_stops:
        strategy.append(f"⚠️ {', '.join(s['name'] for s in near_stops)} 距止损<3%，密切关注")
    
    big_watch = [s for s in enriched_watch if s['chg_pct'] is not None and s['chg_pct'] > 5]
    for s in big_watch:
        strategy.append(f"观察 {s['name']}({s['code']}) 大涨{fmt_pct(s['chg_pct'])}，关注放量突破")
    
    high_vol = [s for s in enriched_hold if s.get('vol_ratio') is not None and s['vol_ratio'] > 2.5]
    for s in high_vol:
        d = "放量上攻" if (s['chg_pct'] or 0) > 0 else "放量下跌"
        strategy.append(f"{s['name']} 成交量{s['vol_ratio']:.1f}x ({d})")
    
    if not strategy:
        strategy.append("当前无异常信号，持有为主")
    
    for l in strategy: lines.append(l)
    lines.append("")
    
    lines.append("**风险提示：**")
    lines.append("本总结由自动化脚本生成，数据仅供内部参考，不构成投资建议。")
    lines.append(f"数据来源: Sina实时行情 | 历史DB: {latest_db_date or 'N/A'}")
    
    print('\n'.join(lines))

if __name__ == '__main__':
    main()
