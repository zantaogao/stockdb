"""
统一数据源接口
=====================
对外暴露统一查询方法，内部自动决定从 stock.db 还是 tushare.db 查询。
支持前复权价格计算（基于 tushare adj_factor）。

使用方式：
    from core.data_source import DS
    ds = DS()
    
    # 原始日K（优先 stock.db，缺的从 tushare 补）
    daily = ds.get_daily('600519', '2026-01-01', '2026-06-18')
    
    # 前复权日K
    fwd = ds.get_daily_forward('600519', '2026-01-01', '2026-06-18')
    
    # 全市场批量获取
    all_daily = ds.get_all_daily('2026-06-16')
    
    # 股票信息
    info = ds.get_stock_info('600519')
    
    # 财务数据
    income = ds.get_financial('600519', 'income')  # income/balance/cashflow
    
    # 资金流
    mf = ds.get_moneyflow('600519', '2026-01-01', '2026-06-18')
    
    # 估值数据
    val = ds.get_valuation('600519', '2026-06-16')
    
    # 因子数据
    factors = ds.get_factors('600519', '2026-01-01', '2026-06-18')
    
    # 指数日K
    idx = ds.get_index_daily('000001', '2026-01-01', '2026-06-18')
    
    # 涨跌停数据
    limits = ds.get_stk_limit('600519', '2026-01-01', '2026-06-18')
"""
import os
import duckdb
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from core.db import TUSHARE_DB_PATH, get_tushare_db, get_stock_db, get_db, get_db_path


def _ts_code(stock_code: str) -> str:
    """600519 → 600519.SH, 000001 → 000001.SZ"""
    if stock_code.startswith(('6', '68', '9')):
        return f"{stock_code}.SH"
    return f"{stock_code}.SZ"


def _parse_date(d) -> str:
    """统一日期格式为 YYYYMMDD"""
    if d is None:
        return None
    if isinstance(d, (int, str)):
        s = str(d)
        if len(s) == 8:
            return s
    if isinstance(d, date):
        return d.strftime('%Y%m%d')
    s = str(d).replace('-', '')
    return s[:8]


def _fmt_date(d) -> str:
    """日期 → YYYY-MM-DD"""
    if isinstance(d, date):
        return d.strftime('%Y-%m-%d')
    s = str(d).replace('-', '').replace('/', '')
    if len(s) >= 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(d)


class DS:
    """统一数据源"""

    @staticmethod
    def _stock_conn(ro=True):
        """指向 signals.db（v2温层只读）"""
        return duckdb.connect(str(os.path.expanduser('~/.hermes/stockdb/signals.db')), read_only=True)  # v2温层只读

    @staticmethod
    def _tushare_conn(ro=True):
        """现在指向 tushare.db（主力库）— 走 core/db.py 统一入口"""
        from core.db import get_tushare_db
        return get_tushare_db(read_only=ro)

    # ── 日K数据 ──────────────────────────────────────────

    def get_daily(self, stock_code: str, start: str = None,
                  end: str = None) -> List[dict]:
        """
        获取日K数据（从 tushare.db 读取）
        
        Returns:
            [{date, open, close, high, low, volume, amount, change_pct, ...}]
        """
        code = str(stock_code)
        ts = _ts_code(code)
        s = _parse_date(start)
        e = _parse_date(end)

        conn = self._stock_conn()
        query = """
            SELECT trade_date, ts_code, open, close, high, low, 
                   vol as volume, amount, pct_chg as change_pct
            FROM daily WHERE ts_code = ?
        """
        params = [ts]
        if s:
            query += " AND trade_date >= ?"
            params.append(s)
        if e:
            query += " AND trade_date <= ?"
            params.append(e)
        query += " ORDER BY trade_date"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append({
                'date': _fmt_date(r[0]), 'stock_code': code,
                'open': r[2], 'close': r[3], 'high': r[4], 'low': r[5],
                'volume': int(r[6]) if r[6] else 0, 'amount': r[7],
                'change_pct': r[8],
            })

        return result

    def get_daily_forward(self, stock_code: str, start: str = None,
                          end: str = None) -> List[dict]:
        """
        获取前复权日K数据
        前复权 = 原始价格 * 最新adj_factor / 当日adj_factor
        
        使用 tushare.db 中的 daily + adj_factor 表
        """
        code = str(stock_code)

        conn = self._stock_conn()

        # 获取最新 adj_factor
        latest_af = conn.execute("""
            SELECT adj_factor FROM adj_factor 
            WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1
        """, [_ts_code(code)]).fetchone()

        if not latest_af:
            conn.close()
            return self.get_daily(code, start, end)

        latest_af_val = latest_af[0]

        # 从 daily JOIN adj_factor 计算前复权
        query = """
            SELECT d.trade_date, d.open, d.close, d.high, d.low, 
                   d.vol as volume, d.amount, d.pct_chg as change_pct,
                   a.adj_factor,
                   d.open * ? / a.adj_factor as fwd_open,
                   d.close * ? / a.adj_factor as fwd_close,
                   d.high * ? / a.adj_factor as fwd_high,
                   d.low * ? / a.adj_factor as fwd_low
            FROM daily d
            JOIN adj_factor a ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            WHERE d.ts_code = ?
        """
        params = [latest_af_val, latest_af_val, latest_af_val, latest_af_val, _ts_code(code)]
        if start:
            query += " AND d.trade_date >= ?"
            params.append(_parse_date(start))
        if end:
            query += " AND d.trade_date <= ?"
            params.append(_parse_date(end))
        query += " ORDER BY d.trade_date"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append({
                'date': _fmt_date(r[0]), 'stock_code': code,
                'open': r[9], 'close': r[10], 'high': r[11], 'low': r[12],
                'volume': r[5], 'amount': r[6], 'change_pct': r[7],
            })

        return result

    def get_all_daily(self, target_date: str = None) -> List[dict]:
        """
        获取全市场某一天的日K数据（原始价格）
        
        Returns:
            [{stock_code, date, close, change_pct, ...}]
        """
        if target_date:
            d = _parse_date(target_date)
        else:
            d = None

        conn = self._stock_conn()
        query = "SELECT ts_code, trade_date, open, close, high, low, vol as volume, amount, pct_chg as change_pct FROM daily"
        if d:
            query += " WHERE trade_date = ?"
            rows = conn.execute(query, [d]).fetchall()
        else:
            rows = conn.execute(query + " WHERE trade_date = (SELECT MAX(trade_date) FROM daily)").fetchall()
        conn.close()

        return [{
            'stock_code': r[0], 'date': _fmt_date(r[1]),
            'open': r[2], 'close': r[3], 'high': r[4], 'low': r[5],
            'volume': r[6], 'amount': r[7], 'change_pct': r[8],
        } for r in rows]

    # ── 复权因子 ─────────────────────────────────────────

    def get_adj_factor(self, stock_code: str) -> Optional[float]:
        """获取某股票的最新 adj_factor"""
        code = str(stock_code)
        conn = self._stock_conn()
        row = conn.execute("""
            SELECT adj_factor FROM adj_factor 
            WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1
        """, [_ts_code(code)]).fetchone()
        conn.close()
        return row[0] if row else None

    def get_adj_factors(self, stock_code: str, start: str = None,
                        end: str = None) -> List[dict]:
        """获取某股票的 adj_factor 历史"""
        code = str(stock_code)
        conn = self._stock_conn()
        query = "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code = ?"
        params = [_ts_code(code)]
        if start:
            query += " AND trade_date >= ?"
            params.append(_parse_date(start))
        if end:
            query += " AND trade_date <= ?"
            params.append(_parse_date(end))
        query += " ORDER BY trade_date"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [{'date': _fmt_date(r[0]), 'adj_factor': r[1]} for r in rows]

    def forward_price(self, stock_code: str, raw_price: float,
                      price_date: str = None) -> float:
        """
        将原始价格转为前复权价格（使用 tushare.db adj_factor）
        """
        code = str(stock_code)
        conn = self._stock_conn()

        if price_date:
            pd = _parse_date(price_date)
            af_row = conn.execute("""
                SELECT adj_factor FROM adj_factor 
                WHERE ts_code = ? AND trade_date = ?
            """, [_ts_code(code), pd]).fetchone()
        else:
            af_row = conn.execute("""
                SELECT adj_factor FROM adj_factor 
                WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1
            """, [_ts_code(code)]).fetchone()

        latest_af_row = conn.execute("""
            SELECT adj_factor FROM adj_factor 
            WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1
        """, [_ts_code(code)]).fetchone()
        conn.close()

        if not af_row or not latest_af_row:
            return raw_price

        return raw_price * latest_af_row[0] / af_row[0]

    # ── 股票信息 ─────────────────────────────────────────

    def get_stock_info(self, stock_code: str = None) -> List[dict]:
        """
        获取股票基本信息（从 tushare.db stock_basic）
        stock_code 为 None 时返回全部
        """
        conn = self._stock_conn()
        if stock_code:
            rows = conn.execute(
                "SELECT * FROM stock_basic WHERE ts_code = ?",
                [_ts_code(stock_code)]
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM stock_basic").fetchall()
        conn.close()

        if not rows:
            return []

        cols = ['ts_code', 'symbol', 'name', 'area', 'industry',
                'market', 'list_date', 'delist_date', 'is_hs']
        return [dict(zip(cols, r)) for r in rows]

    # ── 财务数据 ─────────────────────────────────────────

    def get_financial(self, stock_code: str, table: str = 'income',
                      report_date: str = None) -> List[dict]:
        """
        获取财务数据
        table: 'income' / 'balance' / 'cashflow'
        """
        tbl_map = {
            'income': 'fin_income',
            'balance': 'fin_balancesheet',
            'cashflow': 'fin_cashflow',
        }
        tbl = tbl_map.get(table, 'fin_income')
        conn = self._stock_conn()

        query = f"SELECT * FROM {tbl} WHERE ts_code = ?"
        params = [_ts_code(str(stock_code))]
        if report_date:
            query += " AND end_date >= ?"
            params.append(_parse_date(report_date))
        query += " ORDER BY end_date DESC"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        if not rows:
            return []

        col_names = [desc[0] for desc in conn.description] if conn.description else None
        # DuckDB fetchall doesn't give col names, use DESCRIBE
        conn2 = self._stock_conn()
        desc = conn2.execute(f"DESCRIBE {tbl}").fetchall()
        conn2.close()
        cols = [d[0] for d in desc]
        return [dict(zip(cols, r)) for r in rows]

    # ── 资金流 ──────────────────────────────────────────

    def get_moneyflow(self, stock_code: str, start: str = None,
                      end: str = None) -> List[dict]:
        """
        获取资金流数据（从 tushare.db moneyflow_raw）
        """
        code = str(stock_code)
        conn = self._stock_conn()

        query = """
            SELECT trade_date, ts_code,
                   buy_sm_amount, sell_sm_amount,
                   buy_md_amount, sell_md_amount,
                   buy_lg_amount, sell_lg_amount,
                   buy_elg_amount, sell_elg_amount,
                   net_mf_amount, net_mf_vol
            FROM moneyflow_raw WHERE ts_code = ?
        """
        params = [_ts_code(code)]
        if start:
            query += " AND trade_date >= ?"
            params.append(_parse_date(start))
        if end:
            query += " AND trade_date <= ?"
            params.append(_parse_date(end))
        query += " ORDER BY trade_date"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append({
                'date': _fmt_date(r[0]), 'stock_code': code,
                'small_in': r[2], 'small_out': r[3],
                'mid_in': r[4], 'mid_out': r[5],
                'large_in': r[6], 'large_out': r[7],
                'super_large_in': r[8], 'super_large_out': r[9],
                'net_amount': r[10], 'net_volume': r[11],
            })

        return result

    # ── 估值数据 ────────────────────────────────────────

    def get_valuation(self, stock_code: str, target_date: str = None) -> List[dict]:
        """
        获取估值数据（从 tushare.db daily_basic）
        """
        ts = _ts_code(stock_code)
        conn = self._stock_conn()

        query = """
            SELECT trade_date, close, turnover_rate, pe, pe_ttm, pb, ps,
                   dv_ratio, total_share, float_share, total_mv, circ_mv
            FROM daily_basic WHERE ts_code = ?
        """
        params = [ts]
        if target_date:
            query += " AND trade_date <= ?"
            params.append(_parse_date(target_date))
        query += " ORDER BY trade_date DESC LIMIT 100"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append({
                'date': _fmt_date(r[0]), 'close': r[1],
                'turnover_rate': r[2], 'pe': r[3], 'pe_ttm': r[4],
                'pb': r[5], 'ps': r[6], 'dv_ratio': r[7],
                'total_share': r[8], 'float_share': r[9],
                'total_mv': r[10], 'circ_mv': r[11],
            })

        return result

    # ── 因子数据 ────────────────────────────────────────

    def get_factors(self, stock_code: str, start: str = None,
                    end: str = None) -> List[dict]:
        """
        获取因子值（从 tushare.db，暂返回空，因子数据在 stock.db）
        """
        return []

    def get_factor_names(self) -> List[str]:
        """获取所有因子名称"""
        return []

    # ── 指数日K ────────────────────────────────────────

    def get_index_daily(self, index_code: str, start: str = None,
                        end: str = None) -> List[dict]:
        """获取指数日K数据（从 tushare.db index_daily_raw）"""
        conn = self._stock_conn()
        query = """
            SELECT date, index_code, open, close, high, low, volume, amount,
                   change_pct
            FROM index_daily WHERE index_code = ?
        """
        params = [str(index_code)]
        if start:
            query += " AND date >= ?"
            params.append(_fmt_date(_parse_date(start)))
        if end:
            query += " AND date <= ?"
            params.append(_fmt_date(_parse_date(end)))
        query += " ORDER BY date"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        return [{
            'date': _fmt_date(r[0]), 'index_code': r[1],
            'open': r[2], 'close': r[3], 'high': r[4], 'low': r[5],
            'volume': r[6], 'amount': r[7], 'change_pct': r[8],
        } for r in rows]

    # ── 涨跌停数据 ─────────────────────────────────────

    def get_stk_limit(self, stock_code: str, start: str = None,
                      end: str = None) -> List[dict]:
        """获取涨跌停数据（stock.db stk_limit）"""
        code = str(stock_code)
        conn = self._stock_conn()

        query = """
            SELECT trade_date, stock_code, up_limit, down_limit
            FROM stk_limit WHERE stock_code = ?
        """
        params = [code]
        if start:
            query += " AND trade_date >= ?"
            params.append(_parse_date(start))
        if end:
            query += " AND trade_date <= ?"
            params.append(_parse_date(end))
        query += " ORDER BY trade_date"

        rows = conn.execute(query, params).fetchall()
        conn.close()

        return [{
            'date': _fmt_date(r[0]), 'stock_code': r[1],
            'up_limit': r[2], 'down_limit': r[3],
        } for r in rows]

    # ── 信号历史（个股页面用）──────────────────────────

    def get_signal_history(self, stock_code: str, start: str = None,
                           end: str = None) -> List[dict]:
        """
        获取某股票的评分历史
        需要 signal_history 表（Phase 1 后续创建）
        """
        conn = self._stock_conn()
        try:
            query = """
                SELECT date, stock_code, fusion_score, reg20, reg40, reg10,
                       gtja_score, deviation120
                FROM signal_history WHERE stock_code = ?
            """
            params = [str(stock_code)]
            if start:
                query += " AND date >= ?"
                params.append(_parse_date(start))
            if end:
                query += " AND date <= ?"
                params.append(_parse_date(end))
            query += " ORDER BY date DESC"

            rows = conn.execute(query, params).fetchall()
            conn.close()

            return [{
                'date': _fmt_date(r[0]), 'stock_code': r[1],
                'fusion_score': r[2], 'reg20': r[3], 'reg40': r[4],
                'reg10': r[5], 'gtja_score': r[6], 'deviation120': r[7],
            } for r in rows]
        except Exception:
            conn.close()
            return []

    def insert_signal_history(self, signals: List[dict]):
        """
        批量写入信号历史
        signals: [{stock_code, date, fusion_score, reg20, ...}]
        """
        conn = self._stock_conn(ro=False)
        try:
            for s in signals:
                conn.execute("""
                    INSERT OR REPLACE INTO signal_history 
                    (date, stock_code, fusion_score, reg20, reg40, reg10,
                     gtja_score, deviation120)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    s.get('date'), s.get('stock_code'),
                    s.get('fusion_score'), s.get('reg20'), s.get('reg40'),
                    s.get('reg10'), s.get('gtja_score'), s.get('deviation120'),
                ])
            conn.commit()
        finally:
            conn.close()

    # ── 龙虎榜 ──────────────────────────────────────────

    def get_dragon_tiger(self, stock_code: str = None,
                         start: str = None, end: str = None) -> List[dict]:
        """获取龙虎榜数据"""
        conn = self._stock_conn()
        query = "SELECT * FROM dragon_tiger WHERE 1=1"
        params = []
        if stock_code:
            query += " AND stock_code = ?"
            params.append(str(stock_code))
        if start:
            query += " AND date >= ?"
            params.append(_parse_date(start))
        if end:
            query += " AND date <= ?"
            params.append(_parse_date(end))
        query += " ORDER BY date DESC"

        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [list(r) for r in rows]
