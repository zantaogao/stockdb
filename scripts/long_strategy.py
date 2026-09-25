#!/usr/bin/env python3
"""
长线策略引擎 v1
60-120天弹性持有 | 持续量价监控 | 随时补入

止损规则（两条任一触发即卖）：
  ① 硬止损: 浮亏超过-15%
  ② 趋势止损: 收盘跌破MA60（上升趋势终结）

量价监控（预警不自动卖）：
  ③ 放量下跌: 量>3倍均量 且 跌>3%
  ④ 缩量滞涨: 量<0.5倍均量 且 涨幅<1%

买入规则：
  - 长线筛选合格（ROE>10%+站MA60+多因子评分TOP）
  - 仓位动态管理（最多同时持有5只）
  - 有仓位余量时随时补入排名最高的
"""
import os, sys, json, duckdb
from datetime import datetime, timedelta

# ── 路径 ──
DB = os.path.expanduser("~/.hermes/stockdb/stock.db")
HOLD_PATH = os.path.expanduser("~/.hermes/stockdb/holdings.json")
SCRIPTS = os.path.expanduser("~/.hermes/stockdb/scripts")
sys.path.insert(0, SCRIPTS)
from importlib import util as import_util
spec = import_util.spec_from_file_location("fupan", f"{SCRIPTS}/复盘.py")
fp = import_util.module_from_spec(spec)
spec.loader.exec_module(fp)

# ── 常量 ──
MAX_POSITIONS = 999        # 持仓不设上限
STOP_LOSS_PCT = -20.0    # 硬止损-20%
HOLD_MIN = 60            # 最短持有天数
HOLD_MAX = 120           # 最长持有天数
VOL_WARN_DOWN = 3.0      # 放量下跌预警: 量>3倍
CHG_WARN_DOWN = -3.0     # 放量下跌预警: 跌>3%
VOL_WARN_STALL = 0.5     # 缩量滞涨预警: 量<0.5倍
CHG_WARN_STALL = 1.0     # 缩量滞涨预警: 涨<1%

# ── 工具函数 ──
def load_json(path, default=None):
    if default is None: default = {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def sina_code(code):
    if code in ('000001', '399001', '399006'):
        return {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006'}[code]
    return f"sh{code}" if code.startswith(("6","68")) else f"sz{code}"

def fetch_price(code):
    """从Sina获取实时价格"""
    import urllib.request
    try:
        url = f"https://hq.sinajs.cn/list={sina_code(code)}"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=5).read()
        text = raw.decode('gbk')
        parts = text.split('"')[1].split(',')
        return float(parts[3]), float(parts[2])  # current, prev_close
    except:
        return None, None

# ── 长线候选获取 ──
def get_long_candidates(conn, top_n=5):
    """获取长线TOP N候选股"""
    today = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()
    if not today: return []
    today_str = today[0].isoformat() if hasattr(today[0], 'isoformat') else str(today[0])
    
    try:
        cand = fp.get_candidates_long(conn, today_str)
        if not cand: return []
        return cand[:top_n]
    except:
        return []

# ── 持仓监控 ──
def check_position(conn, code, info, today_str):
    """
    检查单只持仓的状态
    返回: (action, reason, detail)
      action: 'HOLD' | 'SELL' | 'WARN'
    """
    name = info.get('name', code)
    buy_price = info.get('buy_price')
    buy_date = info.get('buy_date')
    if not buy_price or not buy_date:
        return ('HOLD', '', '')
    
    # 实时价格
    price, _ = fetch_price(code)
    if not price:
        # fallback: 用昨日收盘
        row = conn.execute(f"SELECT close FROM stock_daily WHERE stock_code='{code}' AND date='{today_str}'").fetchone()
        if not row: return ('HOLD', '', '')
        price = row[0]
    
    pnl = (price - buy_price) / buy_price * 100
    held_days = (datetime.now() - datetime.strptime(str(buy_date), '%Y-%m-%d')).days
    
    # 获取技术数据
    row = conn.execute(f"""
        SELECT t.close, m.ma60, t.volume, v.vol_ma20, t.change_pct
        FROM stock_daily t
        LEFT JOIN (SELECT stock_code, AVG(close) as ma60 FROM stock_daily 
            WHERE stock_code='{code}' AND date >= DATE '{today_str}' - 60 AND date < '{today_str}' GROUP BY stock_code) m
            ON t.stock_code = m.stock_code
        LEFT JOIN (SELECT stock_code, AVG(volume) as vol_ma20 FROM stock_daily 
            WHERE stock_code='{code}' AND date >= DATE '{today_str}' - 20 AND date < '{today_str}' GROUP BY stock_code) v
            ON t.stock_code = v.stock_code
        WHERE t.stock_code='{code}' AND t.date='{today_str}'
    """).fetchone()
    
    if not row:
        return ('HOLD', '', f'浮亏{pnl:.1f}% 持有{held_days}天')
    
    close, ma60, vol, vma20, chg = row
    vol_ratio = vol / vma20 if vma20 and vma20 > 0 else 1.0
    
    detail = f"浮亏{pnl:.1f}% 持{held_days}d 收{close:.2f} 量比{vol_ratio:.1f}"
    
    # ── 读取连续跌破MA60天数 ──
    trend_break_days = info.get('trend_break_days', 0)
    last_break_date = info.get('last_break_date', '')
    
    # ── 卖出判断 ──
    # ① 硬止损
    if pnl < STOP_LOSS_PCT:
        return ('SELL', f'硬止损触发({pnl:.1f}%<-{abs(STOP_LOSS_PCT):.0f}%)', detail, trend_break_days, today_str)
    
    # ② 趋势止损: 收盘跌破MA60（需连续3天确认）
    if ma60 and close < ma60:
        if today_str != last_break_date:
            trend_break_days += 1
        if trend_break_days >= 3:
            return ('SELL', f'连续{trend_break_days}天跌破MA60({ma60:.2f})', detail, trend_break_days, today_str)
        else:
            return ('WARN', f'第{trend_break_days}天跌破MA60（需连续3天确认）', detail, trend_break_days, today_str)
    else:
        # 站回MA60以上，重置计数
        if today_str != last_break_date:
            trend_break_days = 0
    
    # ③ 持有到期
    if held_days >= HOLD_MAX:
        return ('SELL', f'持有到期{HOLD_MAX}天', detail)
    
    # ── 预警（不自动卖，但推送提醒） ──
    warns = []
    if chg and chg < CHG_WARN_DOWN and vol_ratio > VOL_WARN_DOWN:
        warns.append(f"放量下跌(量比{vol_ratio:.1f}跌{chg:.1f}%)")
    if chg and abs(chg) < CHG_WARN_STALL and vol_ratio < VOL_WARN_STALL:
        warns.append(f"缩量滞涨(量比{vol_ratio:.1f})")
    if held_days >= HOLD_MIN:
        warns.append(f"已满最短持有{HOLD_MIN}天")
    
    if warns:
        return ('WARN', '; '.join(warns), detail)
    
    return ('HOLD', '', detail)

# ── 每日监控主函数 ──
def monitor(output_json=False):
    """每日持仓监控"""
    conn = duckdb.connect(DB, read_only=True)
    today = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    today_str = today.isoformat() if hasattr(today, 'isoformat') else str(today)
    
    data = load_json(HOLD_PATH)
    positions = data.get('positions', [])
    
    results = {'sell': [], 'warn': [], 'hold': [], 'candidates': []}
    
    # ── 检查现有持仓 ──
    positions_updated = False
    for p in positions:
        if p.get('status') != 'hold':
            # 检查watch: 价格在介入区间内不
            if p.get('status') == 'watch' and p.get('entry_low'):
                price, _ = fetch_price(p['code'])
                if price and p['entry_low'] <= price <= p.get('entry_high', 999):
                    results['candidates'].append(p)
            continue
        
        result = check_position(conn, p['code'], p, today_str)
        # result = (action, reason, detail, trend_break_days)
        action, reason, detail = result[0], result[1], result[2]
        trend_days = result[3] if len(result) > 3 else 0
        
        # 保存连续跌破天数到 holdings.json
        old_days = p.get('trend_break_days', 0)
        if trend_days != old_days or today_str != p.get('last_break_date', ''):
            p['trend_break_days'] = trend_days
            p['last_break_date'] = today_str
            positions_updated = True
        
        entry = {'code': p['code'], 'name': p['name'], 'reason': reason, 'detail': detail}
        if action == 'SELL':
            results['sell'].append(entry)
        elif action == 'WARN':
            results['warn'].append(entry)
        else:
            results['hold'].append(entry)
    
    if positions_updated:
        data['positions'] = positions
        save_json(HOLD_PATH, data)
    
    # ── 检查新候选 ──
    hold_count = len([p for p in positions if p.get('status') == 'hold'])
    if hold_count < MAX_POSITIONS:
        cand = get_long_candidates(conn, top_n=MAX_POSITIONS)
        existing = {p['code'] for p in positions if p.get('status') in ('hold', 'watch')}
        rank = 0
        for c in cand:
            if c['code'] not in existing:
                rank += 1
                score_items = []
                # 收集评分因子
                roe = c.get('roe', 0)
                pe = c.get('pe')
                debt = c.get('debt_ratio', 50)
                fund = c.get('main_30d_yi', 0)
                
                tags = []
                if roe and roe > 20: tags.append('💪高ROE')
                if pe and 0 < pe < 20: tags.append('💰低PE')
                if debt and debt < 30: tags.append('🛡️低负债')
                if fund and fund > 1: tags.append(f'💰主力+{fund}亿')
                
                results['candidates'].append({
                    'code': c['code'], 'name': c['name'],
                    'close': c['close'],
                    'rank': rank,
                    'roe': roe, 'pe': pe, 'debt': debt, 'fund': fund,
                    'tags': ' '.join(tags) if tags else '',
                })
                existing.add(c['code'])
    
    conn.close()
    
    if output_json:
        return results
    
    # ── 输出 ──
    output = []
    now = datetime.now().strftime('%H:%M')
    output.append(f"🔔 {today_str} {now} 长线策略监控")
    output.append("")
    
    if results['sell']:
        output.append("🔴 卖出信号")
        output.append("─" * 40)
        for s in results['sell']:
            output.append(f"  {s['name']}({s['code']}): {s['reason']}")
            output.append(f"    {s['detail']}")
        output.append("")
    
    if results['warn']:
        output.append("⚠️ 预警")
        output.append("─" * 40)
        for w in results['warn']:
            output.append(f"  {w['name']}({w['code']}): {w['reason']}")
            output.append(f"    {w['detail']}")
        output.append("")
    
    if results['hold']:
        output.append("📌 持仓正常")
        for h in results['hold']:
            output.append(f"  {h['name']}({h['code']}): {h['detail']}")
        output.append("")
    
    if results['candidates']:
        output.append("💡 候选排名（多因子评分排序）")
        output.append(f"  {'#':>3} {'名称':<10} {'收盘':>7} {'ROE':>6} {'PE':>7} {'负债':>5} {'主力30d':>8} {'标签'}")
        output.append(f"  {'─'*3} {'─'*10} {'─'*7} {'─'*6} {'─'*7} {'─'*5} {'─'*8} {'─'*15}")
        for c in results['candidates'][:20]:
            if 'rank' in c:
                roe_s = f"{c['roe']:.1f}%" if c.get('roe') else "N/A"
                pe_s = f"{c['pe']:.1f}" if c.get('pe') else "N/A"
                debt_s = f"{c['debt']:.0f}%" if c.get('debt') else "N/A"
                fund_s = f"+{c['fund']:.1f}亿" if c.get('fund') and c['fund'] > 0 else "—"
                output.append(f"  {c['rank']:>3} {c['name']:<10} {c['close']:>7.2f} {roe_s:>6} {pe_s:>7} {debt_s:>5} {fund_s:>8}  {c.get('tags','')}")
            else:
                output.append(f"  ⚡ {c['name']:<10} 在介入区间{c.get('entry_low','?')}-{c.get('entry_high','?')}")
        if len(results['candidates']) > 20:
            output.append(f"  ... 还有{len(results['candidates'])-20}只")
    
    if not any([results['sell'], results['warn'], results['hold'], results['candidates']]):
        return  # 静默
    
    print("\n".join(output))
    return results

# ── 买入操作 ──
def buy(code, price=None):
    """买入一只长线股"""
    conn = duckdb.connect(DB, read_only=True)
    today = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    today_str = today.isoformat() if hasattr(today, 'isoformat') else str(today)
    
    if not price:
        row = conn.execute(f"SELECT close FROM stock_daily WHERE stock_code='{code}' AND date='{today_str}'").fetchone()
        if not row:
            # 用实时价
            p, _ = fetch_price(code)
            if not p:
                print(f"❌ 无法获取{code}价格")
                conn.close()
                return
            price = p
        else:
            price = row[0]
    
    name = conn.execute(f"SELECT stock_name FROM stock_info WHERE stock_code='{code}'").fetchone()
    name = name[0] if name else code
    
    data = load_json(HOLD_PATH)
    positions = data.get('positions', [])
    
    # 检查是否已有
    for p in positions:
        if p['code'] == code and p.get('status') in ('hold', 'watch'):
            print(f"❌ {name}({code}) 已在持仓/观察中")
            conn.close()
            return
    
    # 计算止损（介入区间下15%）
    entry_low = round(price * 0.97, 2)  # 通用介入下限
    stop = round(entry_low * 0.85, 2)
    
    new_pos = {
        'code': code, 'name': name,
        'buy_date': today_str, 'buy_price': round(price, 2),
        'stop_loss': round(stop, 2),
        'target': round(price * 1.5, 2),  # 50%目标
        'status': 'hold',
        'note': f"长线买入 {today_str} 止损{stop:.2f}(MA60/硬止损)"
    }
    positions.append(new_pos)
    data['positions'] = positions
    save_json(HOLD_PATH, data)
    
    print(f"✅ 买入 {name}({code}) @ {price:.2f}")
    print(f"   止损 {stop:.2f} | 目标 {price*1.5:.2f} | 最长持有{HOLD_MAX}天")
    conn.close()

# ── 卖出操作 ──
def sell(code, reason=""):
    """卖出一只持仓"""
    price, _ = fetch_price(code)
    data = load_json(HOLD_PATH)
    positions = data.get('positions', [])
    
    for p in positions:
        if p['code'] == code and p.get('status') == 'hold':
            sell_price = price or p.get('buy_price', 0)
            bp = p.get('buy_price', 0)
            pnl = (sell_price - bp) / bp * 100 if bp else 0
            
            p['status'] = 'sold'
            p['sell_date'] = datetime.now().strftime('%Y-%m-%d')
            p['sell_price'] = round(sell_price, 2)
            p['pnl_pct'] = round(pnl, 2)
            p['note'] = f"{p.get('note','')} | 卖出{reason}"
            
            data['positions'] = positions
            save_json(HOLD_PATH, data)
            
            emoji = "🟢" if pnl > 0 else "🔴"
            print(f"{emoji} 卖出 {p['name']}({code}) @ {sell_price:.2f} 盈亏{pnl:+.2f}%")
            return
    
    print(f"❌ 未找到可卖出的持仓: {code}")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="长线策略引擎")
    parser.add_argument('action', choices=['monitor', 'buy', 'sell', 'candidates'], help='操作')
    parser.add_argument('code', nargs='?', help='股票代码(买入/卖出时)')
    parser.add_argument('--price', type=float, help='买入价格')
    parser.add_argument('--reason', default='', help='卖出原因')
    args = parser.parse_args()
    
    if args.action == 'monitor':
        monitor()
    elif args.action == 'buy' and args.code:
        buy(args.code, args.price)
    elif args.action == 'sell' and args.code:
        sell(args.code, args.reason)
    elif args.action == 'candidates':
        conn = duckdb.connect(DB, read_only=True)
        cand = get_long_candidates(conn, 10)
        conn.close()
        if cand:
            print("长线TOP10候选:")
            for i, c in enumerate(cand, 1):
                print(f"  {i}. {c['name']}({c['code']}) 收{c['close']:.2f} ROE{c.get('roe','?')}% PE{c.get('pe','?')}")
        else:
            print("今日无候选")
