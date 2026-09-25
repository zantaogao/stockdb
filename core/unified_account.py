"""
统一账户模型 v1（单账户）
============================
仅支持 main 单账户（中长线，100万）。
旧 multi-account (short/sim) 已移除。

用法：
    from core.unified_account import AccountStore, migrate_accounts
    store = AccountStore()
    acct = store.load("main")          # 加载账户
    acct.cash = 900000                 # 修改
    store.save(acct)                   # 保存
"""
from __future__ import annotations

import json, os, sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict

BASE = Path.home() / '.hermes' / 'stockdb'
ACCOUNTS_DIR = BASE / 'sim_accounts'


def _sf(v, default=0.0):
    """Safely convert to float; handles None, str, etc."""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _si(v, default=0):
    """Safely convert to int; handles None, str, etc."""
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


# ── 默认配置 ──────────────────────────────────────────────
MAIN_DEFAULTS = {
    "initial_capital": 1000000.0,
    "max_positions": 5,
    "min_cash_reserve": 10000.0,
    "buy_score_threshold": 5.0,
    "buy_score_col": "reg20",
    "buy_max_upside_deviation": 25,
    "position_sizing": {
        "score_high": {"min": 12.0, "pct": 0.25},
        "score_mid": {"min": 8.0, "pct": 0.15},
        "score_low": {"min": 5.0, "pct": 0.10},
    },
    "stop_loss_hard": -12.0,
    "stop_loss_trailing": 8.0,
    "take_profit": 25.0,
    "signal_sell_threshold": -2.0,
    "market_risk_enabled": True,
    "max_same_industry": 2,
    "annual_trading_days": 242,
}


@dataclass
class Position:
    code: str
    name: str
    shares: int
    avg_cost: float
    buy_date: str
    peak_price: float = 0
    stop_loss: float = 0
    target: float = 0
    total_cost: float = 0

    def pnl_pct(self, current_price: float) -> float:
        if self.avg_cost <= 0:
            return 0.0
        return (current_price / self.avg_cost - 1) * 100

    def current_value(self, current_price: float) -> float:
        return self.shares * current_price

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name,
            "shares": self.shares, "avg_cost": self.avg_cost,
            "buy_date": self.buy_date, "peak_price": self.peak_price,
            "stop_loss": self.stop_loss, "target": self.target,
            "total_cost": self.total_cost,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(
            code=d.get("code", ""),
            name=d.get("name", ""),
            shares=_si(d.get("shares")),
            avg_cost=_sf(d.get("avg_cost")),
            buy_date=d.get("buy_date", ""),
            peak_price=_sf(d.get("peak_price")),
            stop_loss=_sf(d.get("stop_loss")),
            target=_sf(d.get("target")),
            total_cost=_sf(d.get("total_cost")),
        )


@dataclass
class Trade:
    date: str
    action: str
    code: str
    name: str
    price: float
    shares: int
    amount: float
    pnl_pct: float = None
    reason: str = ""
    signal_score: float = None
    trade_time: str = ""   # HH:MM:SS 成交时刻（用于非交易时段/T+1 检查）

    def to_dict(self) -> dict:
        d = {
            "date": self.date, "action": self.action,
            "code": self.code, "name": self.name,
            "price": self.price, "shares": self.shares,
            "amount": round(self.amount, 2),
            "pnl_pct": self.pnl_pct, "reason": self.reason,
            "trade_time": self.trade_time,
        }
        if self.signal_score is not None:
            d["signal_score"] = self.signal_score
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Trade":
        return cls(
            date=d.get("date", ""),
            action=d.get("action", ""),
            code=d.get("code", ""),
            name=d.get("name", ""),
            price=_sf(d.get("price")),
            shares=_si(d.get("shares")),
            amount=_sf(d.get("amount")),
            pnl_pct=_sf(d.get("pnl_pct")) if d.get("pnl_pct") is not None else None,
            reason=d.get("reason", ""),
            signal_score=_sf(d.get("signal_score")) if d.get("signal_score") is not None else None,
            trade_time=d.get("trade_time", ""),
        )


class Account:
    """统一账户 — 所有账户类型的超集"""

    def __init__(self, account_id: str, name: str, initial_capital: float,
                 config: dict = None, positions: list = None,
                 trades: list = None, nav_history: list = None,
                 created_at: str = None):
        self.id = account_id
        self.name = name
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = positions or []
        self.trades = trades or []
        self.nav_history = nav_history or []
        self.config = config or {}
        self.created_at = created_at or datetime.now().strftime("%Y-%m-%d")
        self.updated_at = datetime.now().strftime("%Y-%m-%d")

    def total_nav(self, price_map: dict = None) -> float:
        """计算总净值。有 price_map 时用市值，否则用成本价兜底。"""
        if price_map:
            pos_val = sum(p.shares * price_map.get(p.code, p.avg_cost) for p in self.positions)
        else:
            pos_val = sum(p.shares * p.avg_cost for p in self.positions)
        return self.cash + pos_val

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def get_position(self, code: str) -> Position | None:
        return next((p for p in self.positions if p.code == code), None)

    def add_position(self, pos: Position) -> None:
        existing = self.get_position(pos.code)
        if existing:
            total_shares = existing.shares + pos.shares
            total_cost = existing.avg_cost * existing.shares + pos.avg_cost * pos.shares
            existing.avg_cost = round(total_cost / total_shares, 2)
            existing.shares = total_shares
        else:
            self.positions.append(pos)

    def remove_position(self, code: str) -> bool:
        before = len(self.positions)
        self.positions = [p for p in self.positions if p.code != code]
        return len(self.positions) < before

    def record_nav(self, price_map: dict = None) -> dict:
        """记录每日NAV"""
        if price_map:
            pos_val = sum(p.shares * price_map.get(p.code, p.avg_cost) for p in self.positions)
        else:
            pos_val = sum(p.shares * p.avg_cost for p in self.positions)
        nav = self.cash + pos_val
        today = datetime.now().strftime("%Y-%m-%d")
        # ⚠️ 2026-08-15 修复：基准必须取"非今天"的最后一条——盘中多次运行时
        # nav_history[-1] 是今天上次运行的 NAV，会把 JSON returns 存成盘中瞬变而非日收益
        # （run_day 的表写入已用同样口径，两处基准必须一致）
        prev_hist = [h for h in self.nav_history if str(h.get('date', '')).replace('-', '') != today.replace('-', '')]
        prev_entry = prev_hist[-1] if prev_hist else {}
        prev_nav = prev_entry.get("nav") or prev_entry.get("total_value") or self.initial_capital
        daily_ret = round((nav / prev_nav - 1) * 100, 4) if prev_nav > 0 else 0
        entry = {
            "date": today, "nav": round(nav, 2),
            "cash": round(self.cash, 2), "pos_value": round(pos_val, 2),
            "returns": daily_ret,
        }
        existing = next((h for h in self.nav_history
                         if str(h["date"]).replace('-', '') == today.replace('-', '')), None)
        # ⚠️ 2026-09-05 修复：DB 权威加载的 date 是无横杠 YYYYMMDD，today 是 YYYY-MM-DD，
        # 精确匹配永远失配 → 同日必追加两条（无横杠盘中条+有横杠收盘条），下游读 JSON 会挑错
        if existing:
            existing.update(entry)
        else:
            self.nav_history.append(entry)
        return entry

    def to_dict(self) -> dict:
        """序列化 — 兼容所有现有格式"""
        return {
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "positions": [p.to_dict() for p in self.positions],
            # 2026-09-14 修复：脚本可能直接 append 裸 dict 进 trades（如 agent_trade_decision.py），
            # 原写法 t.to_dict() 会抛 AttributeError 导致 JSON 导出整份失败（DB 仍已保存）
            "trades": [(t.to_dict() if hasattr(t, 'to_dict') else t) for t in self.trades[-500:]],
            "nav_history": self.nav_history,
            "config": self.config,
            "id": self.id, "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_old_account_json(self) -> dict:
        """导出为旧版 account.json 格式"""
        return {
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "positions": [
                {
                    "code": p.code, "name": p.name, "shares": p.shares,
                    "avg_cost": p.avg_cost, "buy_date": p.buy_date,
                    "stop_loss": p.stop_loss if p.stop_loss else None,
                    "target": p.target if p.target else None,
                } for p in self.positions
            ],
            "trades": [(t.to_dict() if hasattr(t, 'to_dict') else t) for t in self.trades],
            "nav_history": self.nav_history,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        """从任意旧格式或新格式反序列化"""
        positions = []
        for pd in d.get("positions", []):
            positions.append(Position.from_dict(pd))

        trades = []
        for td in d.get("trades", []):
            try:
                trades.append(Trade.from_dict(td))
            except Exception:
                action = td.get("action", "").lower()
                if action in ("buy", "买入"):
                    action_str = "买入"
                elif action in ("sell", "卖出", "卖"):
                    action_str = "卖出"
                else:
                    continue
                trades.append(Trade(
                    date=td.get("date", ""),
                    action=action_str,
                    code=td.get("code", ""),
                    name=td.get("name", ""),
                    price=_sf(td.get("price")),
                    shares=_si(td.get("shares")),
                    amount=_sf(td.get("amount")),
                    pnl_pct=_sf(td.get("pnl_pct")) if td.get("pnl_pct") is not None else None,
                    reason=td.get("reason", ""),
                    trade_time=td.get("trade_time", ""),
                ))

        nav_history = d.get("nav_history", [])
        config = d.get("config", {})

        acct = cls(
            account_id=d.get("id", "unknown"),
            name=d.get("name", ""),
            initial_capital=_sf(d.get("initial_capital")),
            config=config,
            positions=positions,
            trades=trades,
            nav_history=nav_history,
            created_at=d.get("created_at", ""),
        )
        acct.cash = _sf(d.get("cash"), acct.initial_capital)
        return acct


class AccountStore:
    """账户存储 — DB 优先（ledger.db v2热层），JSON 降级为导出兼容层（2026-08-27 迁移）

    权威数据：
      strategy_accounts_meta   (initial_capital / cash / config)
      strategy_positions       (持仓)
      strategy_accounts 表     (NAV 历史，run_day 已持久化)
      trade_log                (交易流水，run_day 已持久化, strategy=账户id)
    JSON (sim_accounts/<id>.json) 仅作可读导出 + 旧读取方（面板/报告）兼容，
    损坏不再影响运行；load 时 JSON 损坏会备份后抛异常，禁止静默重置成空账户。

    main 账户不走本 store（权威源 = account_balance/holdings，见 exec_agent），
    保持原 JSON 兼容行为不变。
    """

    STATE_DB = BASE / 'ledger.db'  # v2热层账本

    def __init__(self):
        self.dir = ACCOUNTS_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ── DB 基础设施 ──────────────────────────────────────
    def _conn(self):
        import sqlite3
        conn = sqlite3.connect(str(self.STATE_DB), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_schema(self):
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_accounts_meta (
                account_id TEXT PRIMARY KEY,
                name TEXT,
                initial_capital REAL,
                cash REAL,
                config_json TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_positions (
                account_id TEXT,
                code TEXT,
                name TEXT,
                shares INTEGER,
                avg_cost REAL,
                buy_date TEXT,
                peak_price REAL,
                stop_loss REAL,
                target REAL,
                total_cost REAL,
                updated_at TEXT,
                PRIMARY KEY (account_id, code)
            )
        """)
        conn.commit()
        conn.close()

    def get_path(self, account_id: str) -> Path:
        return self.dir / f"{account_id}.json"

    def load(self, account_id: str) -> Account:
        """DB 优先加载；DB 无记录 → JSON 自动导入；JSON 也损坏 → 备份并抛异常（不静默重置）"""
        if account_id == 'main':
            # main 权威源在 ledger.db 的 account_balance/holdings（exec_agent 专用），
            # store 仅作 JSON 兼容层，保持原行为
            return self._load_json(account_id)
        conn = self._conn()
        row = conn.execute(
            "SELECT name, initial_capital, cash, config_json, created_at "
            "FROM strategy_accounts_meta WHERE account_id=?", (account_id,)).fetchone()
        if row:
            acct = Account(
                account_id, row[0] or account_id, _sf(row[1], 1_000_000),
                config=json.loads(row[3] or '{}'), created_at=row[4] or '')
            acct.cash = _sf(row[2], acct.initial_capital)
            for r in conn.execute(
                "SELECT code, name, shares, avg_cost, buy_date, peak_price, stop_loss, target, total_cost "
                "FROM strategy_positions WHERE account_id=? ORDER BY code", (account_id,)).fetchall():
                acct.positions.append(Position(
                    code=r[0], name=r[1] or '', shares=_si(r[2]), avg_cost=_sf(r[3]),
                    buy_date=r[4] or '', peak_price=_sf(r[5]), stop_loss=_sf(r[6]),
                    target=_sf(r[7]), total_cost=_sf(r[8])))
            # NAV 历史 ← strategy_accounts（run_day 已持久化）
            for r in conn.execute(
                "SELECT date, nav, cash, pos_value, daily_ret FROM strategy_accounts "
                "WHERE account_id=? ORDER BY date", (account_id,)).fetchall():
                acct.nav_history.append({"date": r[0], "nav": r[1], "cash": r[2],
                                         "pos_value": r[3], "returns": r[4]})
            # 交易流水 ← trade_log（run_day 已持久化，strategy=账户id）
            for r in conn.execute(
                "SELECT trade_date, direction, code, name, price, quantity, amount, "
                "trade_time, signal_score, notes FROM trade_log WHERE strategy=? ORDER BY id",
                (account_id,)).fetchall():
                acct.trades.append(Trade(
                    date=r[0], action='买入' if r[1] == 'BUY' else '卖出',
                    code=r[2], name=r[3] or '', price=_sf(r[4]), shares=_si(r[5]),
                    amount=_sf(r[6]), trade_time=r[7] or '', signal_score=r[8],
                    reason=r[9] or ''))
            conn.close()
            return acct

        # DB 无记录 → JSON 兼容（迁移前旧数据，自动导入 DB）
        path = self.get_path(account_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                acct = Account.from_dict(data)
                conn.close()
                self.save(acct)  # 导入 DB
                return acct
            except Exception as e:
                bak = path.with_name(f"{account_id}.json.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}")
                try:
                    path.rename(bak)
                except Exception:
                    pass
                conn.close()
                raise RuntimeError(
                    f"{account_id} JSON 损坏且 DB 无记录: {e}（损坏文件已备份 {bak.name}，禁止静默重置）") from e
        conn.close()
        # 全新账户
        defaults = {"main": {"name": "中长线", "config": MAIN_DEFAULTS},
                    }.get(account_id, {"name": account_id, "config": {}})
        cap = defaults["config"].get("initial_capital", 1000000)
        return Account(account_id, defaults["name"], cap, defaults["config"])

    def _load_json(self, account_id: str) -> Account:
        """纯 JSON 加载（main 专用兼容路径）"""
        path = self.get_path(account_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return Account.from_dict(data)
            except Exception as e:
                bak = path.with_name(f"{account_id}.json.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}")
                try:
                    path.rename(bak)
                except Exception:
                    pass
                raise RuntimeError(
                    f"{account_id} JSON 损坏: {e}（已备份 {bak.name}，请检查 main 数据源）") from e
        defaults = {"name": "中长线", "config": MAIN_DEFAULTS}
        cap = defaults["config"].get("initial_capital", 1000000)
        return Account(account_id, defaults["name"], cap, defaults["config"])

    def save(self, account: Account) -> None:
        """写 DB（单事务原子）；JSON 导出兼容层（原子写 .tmp→replace，失败不阻断）"""
        if account.id == 'main':
            self._save_json(account)
            return
        conn = self._conn()
        try:
            now = datetime.now().isoformat(timespec='seconds')
            conn.execute("""
                INSERT INTO strategy_accounts_meta
                    (account_id, name, initial_capital, cash, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    name=excluded.name, initial_capital=excluded.initial_capital,
                    cash=excluded.cash, config_json=excluded.config_json,
                    updated_at=excluded.updated_at
            """, (account.id, account.name, account.initial_capital, account.cash,
                  json.dumps(account.config, ensure_ascii=False), account.created_at, now))
            conn.execute("DELETE FROM strategy_positions WHERE account_id=?", (account.id,))
            for p in account.positions:
                conn.execute("""
                    INSERT INTO strategy_positions
                        (account_id, code, name, shares, avg_cost, buy_date,
                         peak_price, stop_loss, target, total_cost, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (account.id, p.code, p.name, p.shares, p.avg_cost, p.buy_date,
                      p.peak_price, p.stop_loss, p.target, p.total_cost, now))
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.close()
            raise RuntimeError(f"账户 {account.id} 写 DB 失败（未改任何数据）: {e}") from e
        conn.close()
        self._save_json(account)

    def _save_json(self, account: Account) -> None:
        """JSON 导出（原子写：.tmp → os.replace；失败仅警告，DB 已是权威）"""
        try:
            path = self.get_path(account.id)
            tmp = path.with_name(f"{account.id}.json.tmp")
            tmp.write_text(json.dumps(account.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(str(tmp), str(path))
        except Exception as e:
            print(f"  ⚠️ {account.id} JSON 导出失败（不影响运行，DB 已保存）: {e}")
        account.updated_at = datetime.now().strftime("%Y-%m-%d")

    def list_all(self) -> list:
        """列出所有账户ID（JSON glob，save 总会导出 JSON，等价于账户列表）"""
        if not self.dir.exists():
            return []
        return [f.stem for f in self.dir.glob("*.json")]

    def get_all_accounts(self) -> dict:
        """加载所有账户"""
        accts = {}
        for aid in self.list_all():
            accts[aid] = self.load(aid)
        return accts


# ── 迁移函数 ──────────────────────────────────────────────
def migrate_accounts() -> dict:
    """
    从三个旧文件迁移到统一账户格式。
    每账户保留所有现有数据，不破坏原有逻辑。
    """
    store = AccountStore()
    results = {}

    # 1. account.json → main
    acct_path = BASE / 'account.json'
    if acct_path.exists():
        try:
            data = json.loads(acct_path.read_text(encoding="utf-8"))
            if "config" not in data:
                data["config"] = MAIN_DEFAULTS
            data["id"] = "main"
            data["name"] = "中长线"
            data["created_at"] = data.get("created_at", "2026-06-02")
            data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
            acct = Account.from_dict(data)
            store.save(acct)
            results["main"] = f"✅ 迁移 {len(acct.positions)} 持仓, {len(acct.trades)} 交易"
            (acct_path.with_suffix('.json.bak')).write_text(
                acct_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        except Exception as e:
            results["main"] = f"❌ 迁移失败: {e}"
    else:
        defaults = {"name": "中长线", "config": MAIN_DEFAULTS}
        cap = defaults["config"].get("initial_capital", 1000000)
        acct = Account("main", defaults["name"], cap, defaults["config"])
        store.save(acct)
        results["main"] = "🆕 创建默认账户"

    # 合并 auto_trade_log.json 到各账户的trades
    log_path = BASE / 'auto_trade_log.json'
    if log_path.exists():
        try:
            log_data = json.loads(log_path.read_text(encoding="utf-8"))
            trades = log_data.get("trades", []) if isinstance(log_data, dict) else []
            if trades:
                main_acct = store.load("main")
                for t in trades:
                    if isinstance(t, dict) and t.get("action") and t.get("code"):
                        action = t.get("action", "").lower()
                        if action in ("buy", "买入"):
                            action_str = "买入"
                        elif action in ("sell", "卖出", "卖"):
                            action_str = "卖出"
                        else:
                            continue
                        trade = Trade(
                            date=t.get("date", ""),
                            action=action_str,
                            code=t.get("code", ""),
                            name=t.get("name", ""),
                            price=_sf(t.get("price")),
                            shares=_si(t.get("shares")),
                            amount=_sf(t.get("amount")),
                            pnl_pct=_sf(t.get("pnl_pct")) if t.get("pnl_pct") is not None else None,
                            reason=t.get("reason", ""),
                        )
                        if action_str == "买入" and t.get("score"):
                            trade.signal_score = _sf(t["score"])
                        main_acct.trades.append(trade)
                store.save(main_acct)
                results["main"] += f" + {len(trades)} 条自动交易日志"
        except Exception as e:
            results["auto_trade_log"] = f"⚠️ 合并日志失败: {e}"

    return results


if __name__ == '__main__':
    print("迁移账户数据...")
    results = migrate_accounts()
    for aid, status in results.items():
        print(f"  {aid}: {status}")
    print("\n验证加载:")
    store = AccountStore()
    for aid in store.list_all():
        acct = store.load(aid)
        nav = acct.cash + sum(p.shares * p.avg_cost for p in acct.positions)
        print(f"  {aid}: {acct.name} | 现金{acct.cash:,.0f} | 持仓{len(acct.positions)}只 | NAV≈{nav:,.0f}")
