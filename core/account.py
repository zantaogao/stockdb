"""
统一账户/持仓管理
"""
import json
from pathlib import Path
from core.prices import get_price, fetch_close_from_db

BASE = Path.home() / '.hermes' / 'stockdb'
HOLD_PATH = BASE / 'holdings.json'
ACCT_PATH = BASE / 'account.json'


def _state_conn():
    """热层 ledger.db 连接（统一入口; 2026-08-29 修: 原误用 duckdb 连 SQLite 文件）"""
    from core.db import connect_ledger
    return connect_ledger()


def get_holdings_from_db():
    """从 ledger.db 读持仓（v2热层）"""
    try:
        conn = _state_conn()
        rows = conn.execute("""
            SELECT code, name, status, buy_date, avg_cost, shares, latest_price, pnl, pnl_pct, update_time
            FROM holdings WHERE status='hold'
        """).fetchall()
        conn.close()
        return [
            {
                'code': r[0], 'name': r[1], 'status': r[2],
                'buy_date': r[3], 'avg_cost': r[4] or 0, 'shares': r[5] or 0
            }
            for r in rows
        ]
    except:
        # fallback 到 JSON
        return get_holdings_from_json()


def get_watchlist_from_db():
    """从 ledger.db 读观察名单（v2热层）"""
    try:
        conn = _state_conn()
        rows = conn.execute("SELECT ts_code FROM watchlist WHERE status='watch_active'").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except:
        return []


def save_holdings_to_db(positions):
    """把持仓写回 ledger.db（v2热层）"""
    try:
        conn = _state_conn()
        for p in positions:
            conn.execute("""
                INSERT OR REPLACE INTO holdings (code, name, status, buy_date, avg_cost, shares)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [p['code'], p.get('name', ''), 'hold', p.get('buy_date', ''), p.get('avg_cost', 0), p.get('shares', 0)])
        conn.execute("CHECKPOINT")
        conn.close()
    except Exception as e:
        print(f"保存持仓到 ledger.db 失败: {e}")


def load_account():
    """加载账户数据（统一格式：sim_accounts/main.json，旧 account.json 已退役）"""
    new_path = BASE / 'sim_accounts' / 'main.json'
    if new_path.exists():
        return json.loads(new_path.read_text(encoding='utf-8'))
    if ACCT_PATH.exists():
        return json.loads(ACCT_PATH.read_text(encoding='utf-8'))
    return None


def save_account(acct):
    """保存账户数据（统一格式：sim_accounts/main.json，旧 account.json 已退役）"""
    new_path = BASE / 'sim_accounts' / 'main.json'
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text(json.dumps(acct, ensure_ascii=False, indent=2), encoding='utf-8')


def create_account():
    """创建默认账户"""
    return {
        "initial_capital": 1000000.0,
        "cash": 1000000.0,
        "positions": [],
        "trades": [],
        "nav_history": [],
    }


def calc_nav(acct, price_map):
    """计算总资产和持仓市值"""
    pos_val = 0
    for p in acct.get('positions', []):
        cp = price_map.get(p['code'])
        if cp:
            pos_val += cp * p['shares']
    nav = acct.get('cash', 0) + pos_val
    return nav, pos_val


def update_nav(acct, price_map):
    """更新净值记录"""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    nav, pos_val = calc_nav(acct, price_map)
    
    history = acct.get('nav_history', [])
    # 2026-09-05: 日期去重统一做横杠归一（同 unified_account.record_nav，防同日双记录）
    existing = next((h for h in history
                     if str(h['date']).replace('-', '') == today.replace('-', '')), None)
    entry = {
        "date": today,
        "nav": nav,
        "cash": acct.get('cash', 0),
        "position_value": round(pos_val, 2),
    }
    if existing:
        existing.update(entry)
    else:
        history.append(entry)
    if len(history) > 365:
        history = history[-365:]
    acct['nav_history'] = history


def get_price_dict(codes):
    """批量获取价格，返回 {code: price}"""
    from core.prices import fetch_prices_batch
    return fetch_prices_batch(codes)


def do_buy(acct, code, name, price, shares=None):
    """执行买入"""
    if not shares:
        # 自动计算可买数量
        max_shares = int(acct['cash'] / price / 100) * 100
        if max_shares <= 0:
            return False, "现金不足"
        shares = min(max_shares, int(acct['cash'] * 0.5 / price / 100) * 100)
        if shares <= 0:
            return False, "现金不足"
    
    cost = price * shares
    if cost > acct['cash']:
        return False, f"现金不足: 需{cost:.0f}, 有{acct['cash']:.0f}"
    
    from datetime import datetime
    acct['cash'] -= cost
    
    # 查找现有持仓
    existing = next((p for p in acct['positions'] if p['code'] == code), None)
    if existing:
        # 摊平成本
        total_shares = existing['shares'] + shares
        total_cost = existing['avg_cost'] * existing['shares'] + cost
        existing['avg_cost'] = round(total_cost / total_shares, 2)
        existing['shares'] = total_shares
    else:
        acct['positions'].append({
            "code": code,
            "name": name,
            "shares": shares,
            "avg_cost": round(price, 2),
            "buy_date": datetime.now().strftime("%Y-%m-%d"),
        })
    
    acct['trades'].append({
        "action": "买入",
        "code": code,
        "name": name,
        "price": round(price, 2),
        "shares": shares,
        "amount": round(cost, 2),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pnl": None,
    })
    
    return True, f"买入 {code} {shares}股 @ {price:.2f}"


def do_sell(acct, code, price, shares=None):
    """执行卖出"""
    pos = next((p for p in acct['positions'] if p['code'] == code), None)
    if not pos:
        return False, f"未持有 {code}"
    
    sell_shares = shares if shares and shares <= pos['shares'] else pos['shares']
    pnl = round((price - pos['avg_cost']) / pos['avg_cost'] * 100, 2)
    amount = price * sell_shares
    
    acct['cash'] += amount
    pos['shares'] -= sell_shares
    
    from datetime import datetime
    acct['trades'].append({
        "action": "卖出",
        "code": code,
        "name": pos.get('name', ''),
        "price": round(price, 2),
        "shares": sell_shares,
        "amount": round(amount, 2),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pnl": pnl,
    })
    
    if pos['shares'] <= 0:
        acct['positions'] = [p for p in acct['positions'] if p['code'] != code]
    
    return True, f"卖出 {code} {sell_shares}股 @ {price:.2f}, 盈亏 {pnl:+.2f}%"


def sync_from_holdings():
    """从 ledger.db 同步持仓到 account.json"""
    try:
        acct = load_account()
        if not acct:
            acct = create_account()
        
        hold_positions = get_holdings_from_db()
        
        acct['positions'] = hold_positions
        save_account(acct)
        return True
    except:
        return False


def get_holdings_from_json():
    """从 holdings.json 读持仓（兼容旧代码）"""
    if not HOLD_PATH.exists():
        return []
    try:
        data = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
        return data.get('positions', [])
    except:
        return []
    
