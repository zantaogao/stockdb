#!/usr/bin/env python3
"""
执行 Agent — 交易指令执行
============================
功能：
1. 读取 orders/pending.json 待执行订单
2. 处理：滑点计算、A股手整数规则（100股）、资金校验
3. 执行：更新账户状态、记录交易、写 NAV
4. 输出：执行结果 orders/executed.json
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import subprocess
from datetime import datetime
from typing import List, Dict, Optional

import sqlite3
import duckdb

from core.db import TUSHARE_DB_PATH, get_tushare_db, connect_ledger
from core.data_source import DS
from core.prices import get_price
from core.unified_account import Account, Position, Trade, AccountStore, MAIN_DEFAULTS


BASE = Path.home() / '.hermes' / 'stockdb'
ORDERS_DIR = BASE / 'orders'
ORDERS_DIR.mkdir(exist_ok=True)


def _load_main_from_db() -> Account:
    """主账户从 ledger.db 读取（v2热层单一源，2026-08-03 统一——与 intraday_decision 决策层同一数据源，
    消除 sim_accounts/main.json 双轨）。持仓=holdings(status='hold')，现金=account_balance。"""
    conn = connect_ledger()  # v2热层(统一入口)
    try:
        row = conn.execute(
            "SELECT initial_capital, cash_balance FROM account_balance WHERE account_id='main'"
        ).fetchone()
        initial_capital = float(row[0]) if row and row[0] else 1000000.0
        cash = float(row[1]) if row and row[1] is not None else initial_capital
        positions = []
        for r in conn.execute(
            "SELECT code, name, shares, avg_cost, buy_date, target_price, stop_loss, latest_price "
            "FROM holdings WHERE status='hold' ORDER BY buy_date"):
            shares = int(r[2] or 0)
            avg_cost = float(r[3] or 0)
            positions.append(Position(
                code=r[0], name=r[1] or '', shares=shares, avg_cost=avg_cost,
                buy_date=str(r[4] or '')[:10],
                target=float(r[5] or 0), stop_loss=float(r[6] or 0),
                total_cost=avg_cost * shares,
            ))
    finally:
        conn.close()
    acct = Account('main', '中长线', initial_capital, dict(MAIN_DEFAULTS))
    acct.cash = cash
    acct.positions = positions
    return acct


def load_account(account_file: str) -> Account:
    """加载账户。main 从 ledger.db（v2热层单一源）；策略账户（fusion3f/cmmr 等）仍走 sim_accounts JSON。"""
    if account_file == 'main':
        return _load_main_from_db()
    store = AccountStore()
    return store.load(account_file)


def save_account(account: Account, account_file: str):
    """保存账户。main：状态已由 sync_to_db 落库（DB 单一源，JSON 停用）；策略账户：写 JSON。"""
    if account_file == 'main':
        return
    store = AccountStore()
    store.save(account)


def load_pending_orders() -> List[Dict]:
    """加载待执行订单"""
    pending_file = ORDERS_DIR / 'pending.json'
    if not pending_file.exists():
        return []
    with open(pending_file) as f:
        data = json.load(f)
        # 兼容两种格式：直接数组或{signals: [...]}
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'signals' in data:
            return data['signals']
        else:
            return []


def save_executed(results: List[Dict]):
    """保存执行结果"""
    executed_file = ORDERS_DIR / 'executed.json'
    # 追加模式
    existing = []
    if executed_file.exists():
        with open(executed_file) as f:
            existing = json.load(f)
    
    existing.extend(results)
    
    with open(executed_file, 'w') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def get_pending_timestamp() -> str:
    """读取 pending.json 的 source_timestamp（用于幂等清理）"""
    pending_file = ORDERS_DIR / 'pending.json'
    if not pending_file.exists():
        return ''
    try:
        with open(pending_file) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return str(data.get('source_timestamp', ''))
    except:
        pass
    return ''


def clear_pending(expected_ts: str = ''):
    """
    清除待执行订单（幂等：仅当 pending.json 的 source_timestamp 与执行时一致才删，
    避免 intraday_decision 新写入的订单被误清）
    """
    pending_file = ORDERS_DIR / 'pending.json'
    if not pending_file.exists():
        return
    if expected_ts:
        cur_ts = get_pending_timestamp()
        if cur_ts and cur_ts != expected_ts:
            print(f"  ⏭ pending.json 已更新({cur_ts} != {expected_ts})，保留新订单")
            return
    pending_file.unlink()


def _safe_stop_loss(stop_loss: float, avg_cost: float) -> float:
    """落库兜底：止损价缺失/为0时用成本×0.88（与硬止损-12%同口径），
    保证新买入持仓的跌破止损规则(rule 3)始终生效。"""
    if stop_loss and stop_loss > 0:
        return stop_loss
    try:
        return round(float(avg_cost) * 0.88, 2) if avg_cost else 0.0
    except (TypeError, ValueError):
        return 0.0


def sync_to_db(account: Account, results: List[Dict]):
    """同步账户状态到 ledger.db（v2热层）"""
    STATE_DB = BASE / 'ledger.db'  # v2热层
    try:
        conn = connect_ledger()  # 统一入口(WAL/busy_timeout 内置)
        
        # 清空当前持仓
        conn.execute("DELETE FROM holdings WHERE status = 'hold'")
        
        # ── 峰值跟踪（2026-08-05 回撤保护）：position_peaks 表持久化 peak_price ──
        # holdings 每轮 DELETE+重插（快照重建），peak 不能存 holdings（会丢）。
        # 独立表 position_peaks(code 主键)：重建时读旧 peak，取 max(旧peak, 现价) 写回。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS position_peaks (
                code TEXT PRIMARY KEY,
                peak_price REAL,
                updated_at TEXT
            )
        """)
        # 读旧 peaks
        old_peaks = {}
        try:
            for r in conn.execute("SELECT code, peak_price FROM position_peaks").fetchall():
                old_peaks[r[0]] = r[1]
        except Exception:
            pass
        
        # 从 tushare.db 获取最新价格 (DuckDB 保持不变)
        tushare_conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
        price_map = {}
        for p in account.positions:
            ts_code = f"{p.code}.SH" if p.code.startswith(('6', '68', '9')) else f"{p.code}.SZ"
            row = tushare_conn.execute(
                "SELECT close FROM daily WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1",
                [ts_code]
            ).fetchone()
            price_map[p.code] = row[0] if row else p.avg_cost
        tushare_conn.close()
        
        # 插入持仓（同时更新 current_price 和 peak）
        now = datetime.now().isoformat()
        today = datetime.now().strftime('%Y-%m-%d')
        for p in account.positions:
            latest_price = price_map.get(p.code, p.avg_cost)
            # 更新 Position 的 current_price
            if hasattr(p, 'current_price'):
                p.current_price = latest_price
            # 峰值更新（2026-08-07 修复重新买入残留旧峰）：
            #   今天全新建仓（buy_date==today）→ 重置 peak，不用旧峰——防"卖出后再买入同 code"
            #   残留旧峰值，新仓成本低时触发 R3 回撤止盈误杀（旧清理逻辑 DELETE NOT IN 只清不在持仓的 code）
            #   加仓（buy_date 为历史日期）→ 保留旧峰继续累积
            old_peak = old_peaks.get(p.code) or 0
            if str(p.buy_date or '')[:10] == today:
                new_peak = max(latest_price, p.avg_cost)
                # 覆盖式写入（excluded 直接 SET——不能用 MAX，否则旧峰残留）
                conn.execute("""
                    INSERT INTO position_peaks (code, peak_price, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET peak_price = excluded.peak_price, updated_at = excluded.updated_at
                """, (p.code, new_peak, now))
            else:
                new_peak = max(old_peak, latest_price, p.avg_cost)
                conn.execute("""
                    INSERT INTO position_peaks (code, peak_price, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET peak_price = MAX(position_peaks.peak_price, ?), updated_at = ?
                """, (p.code, new_peak, now, latest_price, now))
            conn.execute("""
                INSERT INTO holdings (code, name, shares, avg_cost, buy_date, status, latest_price, update_time, target_price, stop_loss)
                VALUES (?, ?, ?, ?, ?, 'hold', ?, ?, ?, ?)
            """, (p.code, p.name, p.shares, p.avg_cost, p.buy_date, latest_price, now,
                  getattr(p, 'target', 0) or 0,
                  _safe_stop_loss(getattr(p, 'stop_loss', 0) or 0, p.avg_cost)))
        
        # 计算持仓市值（用实时价）
        total_position_value = sum(p.shares * price_map.get(p.code, p.avg_cost) for p in account.positions)
        
        # 清理已卖出持仓的 peak（重新买入时不残留旧峰，2026-08-05 回撤保护）
        held_codes = [p.code for p in account.positions]
        if held_codes:
            ph = ','.join(['?'] * len(held_codes))
            conn.execute(f"DELETE FROM position_peaks WHERE code NOT IN ({ph})", held_codes)
        else:
            conn.execute("DELETE FROM position_peaks")
        
        # 查最大 trade_log id（2026-08-24 修复：原按当天范围 MAX，跨日期重复 id；
        # 改全表 MAX 保证全局唯一——现有数据已 UPDATE id=rowid 重编号）
        max_id = conn.execute("SELECT MAX(id) FROM trade_log").fetchone()[0] or 0
        
        # 读取当天主账户现有记录（2026-08-03 修复：不再 DELETE+重插——
        # 原逻辑会清掉当天更早批次的成交记录且 trade_time 漂移到最后一次运行时刻）
        existing_today = {}
        for row in conn.execute(
            "SELECT code, direction, id FROM trade_log WHERE trade_date = ? AND (strategy IS NULL OR strategy = 'main')",
            (today,)).fetchall():
            existing_today[(row[0], row[1])] = row[2]
        
        # 同步今日成交（幂等 UPSERT：同 code+direction 更新价格数量、保留首写 trade_time；新增则插入）
        new_id = max_id
        for i, r in enumerate(results):
            if r.get('status') != 'EXECUTED':
                continue
            direction = 'BUY' if r.get('action') == 'BUY' else 'SELL'
            key = (r.get('stock_code'), direction)
            now_ts = datetime.now().strftime('%H:%M:%S')
            _reason = (str(r.get('reason') or '').strip()[:80]) or 'auto_sync'
            if key in existing_today:
                # 已存在：更新价格/数量/金额，trade_time 用 COALESCE 保留首写（空则补 now）
                # 2026-09-11：notes 也写规则原因（原有的真实原因保留，只覆盖空/占位值）
                conn.execute("""
                    UPDATE trade_log SET price=?, quantity=?, amount=?, trade_time=COALESCE(trade_time, ?),
                        notes=CASE WHEN notes IS NULL OR notes='' OR notes='auto_sync' THEN ? ELSE notes END
                    WHERE id=?
                """, (r.get('price', 0), r.get('shares', 0),
                      r.get('total_cost') or r.get('amount') or r.get('revenue', 0), now_ts, _reason,
                      existing_today[key]))
            else:
                new_id += 1
                conn.execute("""
                    INSERT INTO trade_log (id, code, name, direction, quantity, price, amount, trade_date, trade_time, strategy, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'main', ?)
                """, (new_id, r.get('stock_code'), r.get('stock_name'), direction,
                      r.get('shares', 0), r.get('price', 0), r.get('total_cost') or r.get('amount') or r.get('revenue', 0), today,
                      now_ts, _reason))
        # ── 2026-09-11 新增：执行明细落库（execution_logs 原为空表 → 事后无法查执行/废单原因）──
        for r in results:
            try:
                _dir = 'BUY' if r.get('action') in ('BUY', 'ADD') else 'SELL'
                conn.execute("""
                    INSERT INTO execution_logs
                    (exec_id, signal_id, ts_code, direction, exec_price, exec_quantity, exec_time, status, error_msg)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (f"{today}_{r.get('stock_code')}_{_dir}", r.get('signal_id'), r.get('stock_code'),
                      _dir, r.get('price', 0), r.get('shares', 0), now_ts,
                      r.get('status'), (r.get('error') or None)))
            except Exception as _e:
                print(f"  ⚠️ execution_logs 写入失败({r.get('stock_code')}): {_e}")
        
        # 清空并更新账户余额
        conn.execute("DELETE FROM account_balance WHERE account_id = ?", (account.id,))
        cash = account.cash
        total_assets = cash + total_position_value  # 现金 + 持仓市值
        
        conn.execute("""
            INSERT INTO account_balance (account_id, account_name, initial_capital, cash_balance, total_value, last_update)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (account.id, account.name, account.initial_capital, cash, total_assets, now))
        
        conn.commit()
        conn.close()
        print(f"  ✅ 已同步到 ledger.db")
        
        # ── 更新 watchlist 状态 ──
        try:
            wconn = connect_ledger()  # 统一入口
            wconn.execute("PRAGMA busy_timeout=15000")
            for r in results:
                if r.get('status') != 'EXECUTED':
                    continue
                code = r.get('stock_code')
                action = r.get('action')
                if action == 'BUY':
                    updated = wconn.execute(
                        "UPDATE watchlist SET status='bought' WHERE ts_code=? AND status='pending'",
                        (code,)
                    ).rowcount
                    if updated:
                        print(f"  📝 watchlist {code} → bought")
                elif action == 'SELL':
                    updated = wconn.execute(
                        "UPDATE watchlist SET status='archived' WHERE ts_code=? AND status='bought'",
                        (code,)
                    ).rowcount
                    if updated:
                        print(f"  📝 watchlist {code} → archived")
            wconn.commit()
            wconn.close()
        except Exception as we:
            print(f"  ⚠️  watchlist 状态更新失败：{we}")
    except Exception as e:
        print(f"  ⚠️  DB 同步失败：{e}")


def get_stock_name(code: str) -> str:
    """获取股票名称"""
    try:
        conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
        row = conn.execute(
            "SELECT stock_name FROM stock_info WHERE stock_code = ?",
            [code]
        ).fetchone()
        conn.close()
        return row[0] if row else code
    except:
        return code


def execute_order(order: Dict, account: Account, ds: DS) -> Dict:
    """
    执行单条订单
    
    Returns: 执行结果
    """
    code = order['stock_code']
    action = order['action']
    requested_shares = order.get('shares', 0)
    
    # 获取当前价格
    price, prev = get_price(code)
    if not price or price <= 0:
        return {
            **order,
            'status': 'FAILED',
            'error': f'无法获取 {code} 价格',
            'executed_at': datetime.now().isoformat(),
        }
    
    stock_name = order.get('stock_name', get_stock_name(code))
    
    # A股 100 股整数规则
    shares = int(requested_shares / 100) * 100
    
    result = {
        **order,
        'stock_name': stock_name,
        'price': price,
        'requested_shares': requested_shares,
        'shares': shares,
        'status': 'PENDING',
    }
    
    try:
        if action == 'BUY':
            # 买入：先算后改（2026-08-24 原子化重构——任何异常必须发生在账户状态变更之前，
            # 杜绝"部分变更后抛错 → sync_to_db 覆盖 → 账实分裂"）
            cost = shares * price
            # 滑点 + 手续费 (0.03%)
            total_cost = cost * 1.0003
            
            if total_cost > account.cash:
                # 资金不足，调整数量
                max_shares = int(account.cash / price / 100) * 100
                if max_shares <= 0:
                    result['status'] = 'FAILED'
                    result['error'] = '资金不足'
                    return result
                shares = max_shares
                total_cost = shares * price * 1.0003
            
            # 2026-08-31 硬校验：科创(68)/创业(30) 板最低申报 200 股（执行层兜底）
            if (code.startswith('30') or code.startswith('68')) and shares < 200:
                result['status'] = 'FAILED'
                result['error'] = f'{code} 科创/创业板 100股<200 最低申报，废单拦截'
                return result

            # 2026-09-01 冷却机制：执行层兜底（决策层漏算的冷却票在此拦截，防止损后买回）
            try:
                import sys as _sys
                _sys.path.insert(0, str(BASE / 'scripts'))
                import cooldown as _cd
                _cd_conn = sqlite3.connect(str(BASE / 'ledger.db'), timeout=10)
                try:
                    _cd_conn.execute("ATTACH DATABASE ? AS sig", (str(BASE / 'signals.db'),))
                except Exception:
                    pass
                _cd.ensure_tp_ban_table(_cd_conn)  # 2026-09-02 止盈禁买表
                _blk, _why = _cd.check_cooldown(_cd_conn, code, 'main', price, None)
                if not _blk:
                    # 2026-09-02 止盈(达目标价/回撤止盈)禁买回兜底（用户拍板：与名单无关，全账户）
                    _blk, _why = _cd.check_tp_ban_signal(_cd_conn, code, 'main', _cd.TP_REENTRY_BAN_DAYS)
                _cd_conn.close()
                if _blk:
                    result['status'] = 'FAILED'
                    result['error'] = f'{code} 冷却拦截: {_why}'
                    return result
            except Exception:
                pass  # 冷却检查失败不阻断执行（决策层已检查，兜底尽力）
            
            # 先构造交易记录（构造失败则未改任何状态，安全）
            trade = Trade(
                date=datetime.now().strftime('%Y-%m-%d'),
                action='买入',
                code=code,
                name=stock_name,
                price=price,
                shares=shares,
                amount=total_cost,
            )
            
            # 再执行买入（状态变更）
            if hasattr(account, 'buy'):
                account.buy(code, shares, price)
            else:
                # 手动处理
                account.cash -= total_cost
                # 检查是否已有持仓
                existing_pos = None
                for p in account.positions:
                    if p.code == code:
                        existing_pos = p
                        break
                
                if existing_pos:
                    total_shares = existing_pos.shares + shares
                    total_cost_pos = existing_pos.avg_cost * existing_pos.shares + price * shares
                    existing_pos.shares = total_shares
                    existing_pos.avg_cost = total_cost_pos / total_shares if total_shares > 0 else price
                    existing_pos.current_price = price
                else:
                    new_pos = Position(
                        code=code,
                        name=stock_name,
                        shares=shares,
                        avg_cost=price,
                        buy_date=datetime.now().strftime('%Y-%m-%d'),
                        target=order.get('target_price', 0),
                        stop_loss=order.get('stop_loss', 0),
                    )
                    account.positions.append(new_pos)
            
            account.trades.append(trade)
            
            result['status'] = 'EXECUTED'
            result['total_cost'] = total_cost
            
        elif action == 'SELL':
            # 卖出：先算后改（原子化重构，2026-08-24）
            position = None
            for p in account.positions:
                if p.code == code:
                    position = p
                    break
            
            if not position:
                result['status'] = 'FAILED'
                result['error'] = '无持仓'
                return result
            
            # T+1 制度：当日买入不可当日卖出（执行层兜底，2026-08-03 与策略账户同款保护；
            # 决策层已挡，此处防异常路径如手动写 pending）
            if position.buy_date and str(position.buy_date)[:10] == datetime.now().strftime('%Y-%m-%d'):
                result['status'] = 'FAILED'
                result['error'] = 'T+1: 当日买入不可卖出'
                return result
            
            # 卖出数量不超过持仓
            shares = min(shares, position.shares)
            if shares <= 0:
                result['status'] = 'FAILED'
                result['error'] = '持仓不足'
                return result
            
            # 计算收益
            revenue = shares * price * 0.9997  # 扣手续费
            cost_basis = shares * position.avg_cost
            pnl = revenue - cost_basis
            
            # 先构造交易记录（字段必须 code/name/pnl_pct——Trade dataclass 无 stock_code/
            # stock_name/pnl；构造失败则未改任何状态，安全）
            trade = Trade(
                code=code,
                name=stock_name,
                action='SELL',
                shares=shares,
                price=price,
                amount=revenue,
                pnl_pct=pnl,
                date=datetime.now().strftime('%Y-%m-%d'),
            )
            
            # 再执行卖出（状态变更）
            if position.shares == shares:
                # 全部卖出
                account.positions.remove(position)
            else:
                # 部分卖出
                position.shares -= shares
            
            account.cash += revenue
            account.trades.append(trade)
            
            result['status'] = 'EXECUTED'
            result['revenue'] = revenue
            result['pnl'] = pnl
            result['pnl_pct'] = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0
            
        elif action == 'ADD':
            # 加仓 = 买入：先算后改
            cost = shares * price
            total_cost = cost * 1.0003
            
            if total_cost > account.cash:
                max_shares = int(account.cash / price / 100) * 100
                if max_shares <= 0:
                    result['status'] = 'FAILED'
                    result['error'] = '资金不足'
                    return result
                shares = max_shares
                total_cost = shares * price * 1.0003
            
            # 2026-08-31 硬校验：科创(68)/创业(30) 板最低申报 200 股（执行层兜底）
            if (code.startswith('30') or code.startswith('68')) and shares < 200:
                result['status'] = 'FAILED'
                result['error'] = f'{code} 科创/创业板 100股<200 最低申报，废单拦截'
                return result

            # 2026-09-01 冷却机制：执行层兜底（决策层漏算的冷却票在此拦截，防止损后买回）
            try:
                import sys as _sys
                _sys.path.insert(0, str(BASE / 'scripts'))
                import cooldown as _cd
                _cd_conn = sqlite3.connect(str(BASE / 'ledger.db'), timeout=10)
                try:
                    _cd_conn.execute("ATTACH DATABASE ? AS sig", (str(BASE / 'signals.db'),))
                except Exception:
                    pass
                _cd.ensure_tp_ban_table(_cd_conn)  # 2026-09-02 止盈禁买表
                _blk, _why = _cd.check_cooldown(_cd_conn, code, 'main', price, None)
                if not _blk:
                    # 2026-09-02 止盈(达目标价/回撤止盈)禁买回兜底（用户拍板：与名单无关，全账户）
                    _blk, _why = _cd.check_tp_ban_signal(_cd_conn, code, 'main', _cd.TP_REENTRY_BAN_DAYS)
                _cd_conn.close()
                if _blk:
                    result['status'] = 'FAILED'
                    result['error'] = f'{code} 冷却拦截: {_why}'
                    return result
            except Exception:
                pass  # 冷却检查失败不阻断执行（决策层已检查，兜底尽力）
            
            # 先构造交易记录
            trade = Trade(
                date=datetime.now().strftime('%Y-%m-%d'),
                action='买入',
                code=code,
                name=stock_name,
                price=price,
                shares=shares,
                amount=total_cost,
            )
            
            # 再执行加仓（状态变更）
            if hasattr(account, 'buy'):
                account.buy(code, shares, price)
            else:
                account.cash -= total_cost
                existing_pos = None
                for p in account.positions:
                    if p.code == code:
                        existing_pos = p
                        break
                
                if existing_pos:
                    total_shares = existing_pos.shares + shares
                    total_cost_pos = existing_pos.avg_cost * existing_pos.shares + price * shares
                    existing_pos.shares = total_shares
                    existing_pos.avg_cost = total_cost_pos / total_shares if total_shares > 0 else price
                    existing_pos.current_price = price
            
            account.trades.append(trade)
            
            result['status'] = 'EXECUTED'
            result['total_cost'] = total_cost
            
        elif action == 'REDUCE':
            # 减仓 = 部分卖出：先算后改
            position = None
            for p in account.positions:
                if p.code == code:
                    position = p
                    break
            
            if not position:
                result['status'] = 'FAILED'
                result['error'] = '无持仓'
                return result
            
            shares = min(shares, position.shares)
            if shares <= 0:
                result['status'] = 'FAILED'
                result['error'] = '持仓不足'
                return result
            
            revenue = shares * price * 0.9997
            cost_basis = shares * position.avg_cost
            pnl = revenue - cost_basis
            
            # 先构造交易记录
            trade = Trade(
                code=code,
                name=stock_name,
                action='SELL',
                shares=shares,
                price=price,
                amount=revenue,
                pnl_pct=pnl,
                date=datetime.now().strftime('%Y-%m-%d'),
            )
            
            # 再执行减仓（状态变更）
            if position.shares == shares:
                account.positions.remove(position)
            else:
                position.shares -= shares
            
            account.cash += revenue
            account.trades.append(trade)
            
            result['status'] = 'EXECUTED'
            result['revenue'] = revenue
            result['pnl'] = pnl
            result['pnl_pct'] = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0
            
    except Exception as e:
        result['status'] = 'ERROR'
        result['error'] = str(e)
    
    result['executed_at'] = datetime.now().isoformat()
    return result


def run_execution(account_file: str = 'main') -> List[Dict]:
    """
    执行入口
    """
    print("=" * 50)
    print(f"执行 Agent 运行: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)
    
    # 非交易时段禁止执行订单（统一口径: 9:30-11:30 / 13:00-15:00，见 core/trading_time.py）
    from core.trading_time import in_trading_session
    if not in_trading_session():
        print(f"  [非交易时段，跳过执行]（交易时段: 9:30-11:30 / 13:00-15:00）")
        return []
    
    # 1. 加载待执行订单
    orders = load_pending_orders()
    if not orders:
        print("  无待执行订单")
        return []
    
    pending_ts = get_pending_timestamp()  # 记录本次执行的订单批次时间戳
    print(f"  待执行订单: {len(orders)} 条 (source_timestamp={pending_ts})")
    
    # 订单时效检查（2026-08-03 修复）：批次超过 60 分钟视为过期信号，
    # 跳过执行并清除——防止隔夜滞留订单在次日开盘被按新价格误执行
    if pending_ts:
        try:
            ts_dt = datetime.strptime(pending_ts, '%Y%m%d%H%M%S')
            age_min = (datetime.now() - ts_dt).total_seconds() / 60
            if age_min > 60:
                print(f"  ⏭ 订单批次 {pending_ts} 已过期 ({age_min:.0f} 分钟 > 60)，跳过执行并清除")
                clear_pending(pending_ts)
                return []
        except ValueError:
            pass
    
    # 2. 加载账户
    account = load_account(account_file)
    print(f"  账户: {account.name} 现金: {account.cash:,.0f}")
    
    ds = DS()
    
    # 3. 逐条执行
    results = []
    for order in orders:
        print(f"  执行: {order.get('action')} {order.get('stock_code')} {order.get('shares')}股")
        result = execute_order(order, account, ds)
        results.append(result)
        status = result.get('status')
        print(f"    → {status}")
        if status == 'EXECUTED':
            if order.get('action') == 'BUY':
                print(f"    花费: {result.get('total_cost', 0):,.0f}")
            else:
                print(f"    收益: {result.get('pnl', 0):,.0f}")
            # QQ 实时推送成交（异步不阻塞，失败静默；2026-08-03）
            try:
                subprocess.Popen(
                    [sys.executable, '-B', str(BASE / 'scripts' / 'notify_trade.py'),
                     '主账户', str(order.get('action')), str(order.get('stock_code')),
                     str(result.get('stock_name', '')), str(result.get('shares', 0)),
                     str(result.get('price', 0)),
                     str(result.get('total_cost') or result.get('revenue') or 0),
                     str(result.get('reason', '')),
                     (f"{result.get('pnl', 0):+,.0f}元 ({result.get('pnl_pct', 0):+.2f}%)"
                      if order.get('action') in ('SELL', 'REDUCE') else '')],  # 2026-09-14 卖出/减仓推送带盈亏
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
    
    # 4. 保存
    save_account(account, account_file)
    # （已删除 save_executed：orders/executed.json 只写不读，冗余；执行结果在 trade_log/holdings）
    # 2026-08-28 审计修复：先 sync_to_db（权威源落账）再 clear_pending（删单）。
    # 原顺序 clear→sync 之间崩溃 = 订单已删但账本(ledger.db)未落账（丢单无法发现）；
    # 新顺序最坏 = 订单滞留但 DB 已落账，sync_to_db 写的是绝对值（cash/holdings 快照）天然幂等，
    # 重跑安全，且有 60 分钟订单时效 + 流水自检兜底。
    sync_to_db(account, results)
    clear_pending(pending_ts)
    
    # ── 4.5 成交流水自检（2026-08-24 新增：防"EXECUTED 但流水丢失"静默事故）──
    #     历史教训：SELL Trade 字段 bug 导致持仓已删现金已收但 trade_log 无流水，账实分裂。
    #     这里对每笔 EXECUTED 反向核对 trade_log，缺失即告警（输出会被 cron 记录/健康检查捕获）。
    _missing_log = []
    try:
        _conn = connect_ledger()  # v2热层流水自检(统一入口)
        for r in results:
            if r.get('status') != 'EXECUTED':
                continue
            _dir = 'BUY' if r.get('action') in ('BUY', 'ADD') else 'SELL'
            _c = r.get('stock_code')
            _row = _conn.execute(
                "SELECT 1 FROM trade_log WHERE code=? AND direction=? AND trade_date=? LIMIT 1",
                (_c, _dir, datetime.now().strftime('%Y-%m-%d'))).fetchone()
            if not _row:
                _missing_log.append(f"{_c} {_dir} {r.get('shares', 0)}股")
        _conn.close()
    except Exception as _e:
        print(f"  ⚠️ 流水自检失败: {_e}")
    if _missing_log:
        print(f"  ❌ 流水自检异常：{len(_missing_log)} 笔 EXECUTED 无 trade_log 流水 → {_missing_log}")
        print("     （账实可能分裂！需立即人工核查 sync_to_db 写入逻辑）")
    else:
        print(f"  ✅ 流水自检通过：{sum(1 for r in results if r.get('status') == 'EXECUTED')} 笔成交均有 trade_log 记录")
    
    print(f"\n  执行完成：{len(results)} 条")
    print(f"  成功：{sum(1 for r in results if r['status'] == 'EXECUTED')}")
    print(f"  失败：{sum(1 for r in results if r['status'] != 'EXECUTED')}")
    
    return results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--account', default='main')
    args = parser.parse_args()
    # 交易日历硬闸（2026-09-25 调休休市误交易事故）：非交易日直接退出
    from core.trade_calendar import assert_trading_day
    assert_trading_day('订单执行')
    try:
        run_execution(args.account)
    except Exception as e:
        print(f"⚠️ {e}")
