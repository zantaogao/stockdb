"""
统一信号层 v2
===================
每天只运行一次 signal_agent.py，输出到 signal_history DB 表。
所有组件直接从 DB 读取，不再跑 combined_score.py。

用法：
    from core.signal_fetcher import SignalFetcher
    sf = SignalFetcher()
    signals = sf.fetch()          # 获取最新信号
    sig = sf.get_signal("002342", signals)  # 查某只股票信号
"""
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, date

import duckdb

from core.db import connect_signals, get_tushare_db  # v2: signal_history在温层

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'
# STOCK_DB 已废弃，所有表现在都在 tushare.db 中

_TS_CACHE = {}


def _ts_code(stock_code: str) -> str:
    """600519 → 600519.SH, 000001 → 000001.SZ"""
    if stock_code.startswith(('6', '68', '9')):
        return f"{stock_code}.SH"
    return f"{stock_code}.SZ"


class SignalFetcher:
    """每日信号获取和管理"""

    def fetch(self, ref_date: str = None, top_n: int = 30, min_score: float = 65) -> list:
        """
        从 signal_history DB 表读取信号。

        Args:
            ref_date: 指定日期，默认取最新
            top_n: 最多取前 N 只
            min_score: 最低评分阈值

        Returns:
            [{code, name, fusion, reg20, reg40, reg10,
              cls27_prob, reg_pred, reg40_pred, reg10_pred,
              dev120, price, final_score, fusion_avg}]
        """
        # 1. 从 signals.db 读取 signal_history
        conn = connect_signals(read_only=True)

        if ref_date:
            date_clause = f"AND date = '{ref_date}'"
            # 检查该日期是否有数据
            has_data = conn.execute(
                f"SELECT COUNT(*) FROM signal_history WHERE date = '{ref_date}'"
            ).fetchone()[0]
            if not has_data:
                # 该日期无数据，fallback到最新
                print(f"  ⚠️ 日期 {ref_date} 无数据，使用最新交易日")
                ref_date = None
                date_clause = ""

        if not ref_date:
            latest = conn.execute(
                "SELECT MAX(date) FROM signal_history"
            ).fetchone()[0]
            if not latest:
                conn.close()
                return []
            ref_date = latest
            date_clause = f"AND date = '{latest}'"

        # 2. 从 signal_history 表读取信号
        rows = conn.execute(f"""\n            SELECT sh.stock_code, sh.stock_name, sh.reg20, sh.reg40, sh.reg10,\n                   sh.cls27_prob, sh.reg_pred, sh.reg40_pred, sh.reg10_pred,\n                   sh.final_score, sh.fusion_avg, sh.deviation120,\n                   sh.fusion_score, sh.reg_pred as reg20_raw,\n                   sh.reg40_pred as reg40_raw,\n                   sh.reg10_pred as reg10_raw\n            FROM signal_history sh\n            WHERE sh.final_score >= {min_score}\n              AND (sh.stock_name NOT LIKE '%ST%' OR sh.stock_name IS NULL)\n              {date_clause}\n            ORDER BY sh.final_score DESC, sh.fusion_avg DESC\n            LIMIT {top_n}\n        """).fetchall()
        conn.close()

        if not rows:
            return []

        # 3. 构建信号列表
        signals = []
        for r in rows:
            signals.append({
                'code': r[0],
                'name': r[1] or '',
                'date': str(ref_date),
                'reg20': r[2] or 0,
                'reg40': r[3] or 0,
                'reg10': r[4] or 0,
                'cls27_prob': r[5] or 0.5,
                'reg_pred': r[6] or 0,
                'reg40_pred': r[7] or 0,
                'reg10_pred': r[8] or 0,
                'final_score': r[9] or 0,
                'fusion_avg': r[10] or 0,
                'dev120': r[11] or 0,
                'gtja': r[12] or 50,
                'price': 0,  # 后续从 tushare.db 补充
            })

        # 4. 从 tushare.db 补充价格
        self._add_prices(signals)

        # 5. 缓存一份到 JSON 文件（兼容旧代码）
        self._cache(signals, ref_date)

        return signals

    def fetch_for_holdings(self, held_codes: list, ref_date: str = None) -> dict:
        """
        获取持仓股的信号（按code索引）。
        用于卖出检查。
        """
        if not held_codes:
            return {}

        conn = get_tushare_db()

        if ref_date:
            date_clause = f"AND date = '{ref_date}'"
        else:
            latest = conn.execute(
                "SELECT MAX(date) FROM signal_history"
            ).fetchone()[0]
            if not latest:
                conn.close()
                return {}
            date_clause = f"AND date = '{latest}'"

        placeholders = ','.join([f"'{c}'" for c in held_codes])
        rows = conn.execute(f"""\n            SELECT sh.stock_code, sh.reg20, sh.reg40, sh.reg10,\n                   sh.cls27_prob, sh.reg_pred, sh.reg40_pred, sh.reg10_pred,\n                   sh.final_score, sh.fusion_avg, sh.deviation120\n            FROM signal_history sh\n            WHERE sh.stock_code IN ({placeholders})\n              AND (sh.stock_name NOT LIKE '%ST%' OR sh.stock_name IS NULL)\n              {date_clause}\n        """).fetchall()
        conn.close()

        signals_map = {}
        for r in rows:
            signals_map[r[0]] = {
                'code': r[0],
                'reg20': r[1] or 0,
                'reg40': r[2] or 0,
                'reg10': r[3] or 0,
                'cls27_prob': r[4] or 0.5,
                'reg_pred': r[5] or 0,
                'reg40_pred': r[6] or 0,
                'reg10_pred': r[7] or 0,
                'final_score': r[8] or 0,
                'fusion_avg': r[9] or 0,
                'dev120': r[10] or 0,
            }
        return signals_map

    def get_signal(self, code: str, signals: list) -> dict:
        """根据code查信号"""
        return next((s for s in signals if s.get('code') == code), None)

    def _add_prices(self, signals: list):
        """从 tushare.db 获取每个信号股票的价格"""
        if not signals:
            return

        codes = [s['code'] for s in signals if s['code']]
        if not codes:
            return

        conn = get_tushare_db()
        placeholders = ','.join([f"'{_ts_code(c)}'" for c in codes])

        # 获取最新价格
        rows = conn.execute(f"""\n            SELECT ts_code, close FROM (\n                SELECT ts_code, close,\n                       ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn\n                FROM daily\n                WHERE ts_code IN ({placeholders})\n            ) WHERE rn = 1\n        """).fetchall()

        conn.close()

        price_map = {}
        for r in rows:
            ts_code = r[0]
            stock_code = ts_code.replace('.SH', '').replace('.SZ', '')
            price_map[stock_code] = float(r[1] or 0)

        for s in signals:
            if s['code'] in price_map and price_map[s['code']]:
                s['price'] = price_map[s['code']]

    def _cache(self, signals: list, ref_date: str = None):
        """缓存信号到JSON文件（兼容旧代码）"""
        cache_file = BASE / '_score_cache.json'
        today = str(ref_date or date.today().isoformat())

        cache = {
            "date": today,
            "count": len(signals),
            "scores": {}
        }
        for s in signals:
            cache['scores'][s['code']] = {
                'fusion': s.get('fusion_avg', 0),
                'reg20': s.get('reg_pred', 0),
                'reg40': s.get('reg40_pred', 0),
                'reg10': s.get('reg10_pred', 0),
                'gtja': s.get('gtja', 50),
            }

        cache_file.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2)
        )


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=None)
    parser.add_argument('--top-n', type=int, default=200)
    args = parser.parse_args()

    sf = SignalFetcher()
    signals = sf.fetch(ref_date=args.date, top_n=args.top_n)
    print(f"加载了 {len(signals)} 只信号股票")
    for s in signals[:5]:
        print(f"  {s['code']} {s['name']} "
              f"score={s['final_score']} "
              f"fusion={s['fusion_avg']} "
              f"reg20={s['reg20']} reg40={s['reg40']} reg10={s['reg10']}")
    if len(signals) > 5:
        print(f"  ... and {len(signals) - 5} more")
