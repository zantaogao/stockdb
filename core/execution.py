"""
执行引擎 v1
===================
价格获取 + 滑点处理 + 市场风险评估
"""
import json, os, sys, time, math
from pathlib import Path
from datetime import datetime
from typing import Optional
import numpy as np

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'tushare.db'  # tushare.db 现在作为主力数据库
PRICE_CACHE = {}
PRICE_CACHE_TS = 0
PRICE_CACHE_TTL = 15  # 15秒缓存


class ExecutionEngine:
    """价格获取 + 滑点处理"""

    def __init__(self):
        self._init_tdx_servers()

    def _init_tdx_servers(self):
        """通达信服务器列表"""
        self._tdx_servers = [
            ('180.153.18.172', 80),
            ('106.120.54.81', 7709),
            ('60.191.117.167', 7709),
            ('180.153.18.170', 80),
            ('180.153.18.171', 80),
            ('119.147.212.81', 7709),
        ]
        self._tdx_working = None

    def _sina_code(self, code: str) -> str:
        if code in ('000001', '399001', '399006'):
            return {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006'}[code]
        return f'sh{code}' if code.startswith(('6', '68', '9')) else f'sz{code}'

    def fetch_prices(self, codes: list, ref_date: str = None) -> dict:
        """
        批量获取价格。优先级: Sina实时 > TDX > DB收盘价(指定日期)
        返回: {code: price}
        """
        global PRICE_CACHE, PRICE_CACHE_TS
        now = time.time()
        if now - PRICE_CACHE_TS < PRICE_CACHE_TTL:
            return dict(PRICE_CACHE)

        price_map = {}
        remaining = [c for c in codes if c not in price_map]

        # 1) Sina实时
        pf_map = {}
        for c in remaining:
            prefix = 'sz' if c.startswith(('0', '3', '001')) else 'sh'
            pf_map.setdefault(prefix, []).append(c)
        for prefix, batch in pf_map.items():
            try:
                url = f'https://hq.sinajs.cn/list={",".join(f"{prefix}{c}" for c in batch)}'
                import urllib.request
                req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
                resp = urllib.request.urlopen(req, timeout=8)
                text = resp.read().decode('gbk')
                for item in text.split(';\n'):
                    if not item or '"' not in item:
                        continue
                    try:
                        raw = item.split('"')[1].split(',')
                        if raw and len(raw) > 3 and raw[3]:
                            code_raw = item.split('=')[1].split('_')[-1] if '_' in item else ''
                            if code_raw.startswith(prefix):
                                price_map[code_raw] = float(raw[3])
                    except:
                        pass
            except:
                pass
            time.sleep(0.3)

        # 2) TDX兜底
        missing = [c for c in remaining if c not in price_map]
        if missing and not ref_date:
            price_map = self._fetch_tdx(missing, price_map)

        # 3) DB收盘价兜底
        missing = [c for c in remaining if c not in price_map]
        if missing:
            price_map = self._fetch_from_db(missing, price_map, ref_date)

        PRICE_CACHE = price_map
        PRICE_CACHE_TS = time.time()
        return price_map

    def _fetch_tdx(self, codes: list, existing: dict) -> dict:
        """通达信行情获取"""
        servers = self._tdx_servers[:]
        if self._tdx_working and self._tdx_working in servers:
            servers.insert(0, servers.pop(servers.index(self._tdx_working)))

        for ip, port in servers:
            try:
                from pytdx.hq import TdxHq_API
                api = TdxHq_API(heartbeat=False)
                api.connect(ip, port, time_out=2)
                multi = [(1, c) if c.startswith(('6', '68', '9')) else (0, c) for c in codes]
                tdx_data = api.get_security_quotes_multi(multi)
                api.disconnect()
                if tdx_data:
                    for r in tdx_data:
                        if float(r.get('price', 0)) > 0:
                            existing.setdefault(r['code'], float(r['price']))
                    self._tdx_working = (ip, port)
                    return existing
            except:
                continue
        return existing

    def _fetch_from_db(self, codes: list, existing: dict, ref_date: str = None) -> dict:
        """从DuckDB获取收盘价（从 tushare.db daily 表）"""
        try:
            from core.db import get_tushare_db
            conn = get_tushare_db(read_only=True)
            placeholders = ','.join([f"'{c}.SH'" if c.startswith(('6', '68', '9')) else f"'{c}.SZ'" for c in codes])
            rows = None
            if ref_date:
                rows = conn.execute(f"""
                    SELECT ts_code, close FROM daily
                    WHERE ts_code IN ({placeholders}) AND trade_date='{ref_date}'
                """).fetchall()
                if not rows:
                    # 指定日期无数据，fallback到最新交易日
                    rows = conn.execute(f"""
                        SELECT ts_code, close FROM (
                            SELECT ts_code, close,
                                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
                            FROM daily
                            WHERE ts_code IN ({placeholders})
                        ) WHERE rn = 1
                    """).fetchall()
            if not rows or not any(rows):
                rows = conn.execute(f"""
                    SELECT ts_code, close FROM (
                        SELECT ts_code, close,
                               ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
                        FROM daily
                        WHERE ts_code IN ({placeholders})
                    ) WHERE rn = 1
                """).fetchall()
            conn.close()
            for r in rows:
                ts_code = r[0]
                # ts_code → stock_code (去掉 .SH/.SZ)
                stock_code = ts_code.replace('.SH', '').replace('.SZ', '')
                if stock_code not in existing and r[1]:
                    existing[stock_code] = float(r[1])
        except Exception as e:
            print(f"  ⚠️ DB价格获取失败: {e}")
        return existing

    def apply_slippage(self, price: float, direction: str) -> float:
        """滑点: 买入+0.5%, 卖出-0.5%"""
        if direction == 'buy':
            return round(price * 1.005, 2)
        elif direction == 'sell':
            return round(price * 0.995, 2)
        return price

    def market_risk_score(self) -> dict:
        """
        市场风险评估。
        返回: {score: 0-1, label: "牛市/震荡/熊市"}
        score越高越适合做多
        """
        try:
            from core.db import get_tushare_db
            conn = get_tushare_db(read_only=True)
            rows = conn.execute("""
                SELECT close, vol as volume FROM index_daily_raw
                WHERE ts_code='000001.SH' ORDER BY trade_date DESC LIMIT 120
            """).fetchall()
            conn.close()

            if len(rows) < 120:
                return {'score': 1.0, 'label': '数据不足'}

            closes = [float(r[0]) for r in rows][::-1]
            vols = [float(r[1]) or 0 for r in rows][::-1]

            # 趋势因子 (40%)
            ma60_now = sum(closes[-60:]) / 60
            ma60_prev = sum(closes[-80:-20]) / 60 if len(closes) >= 80 else ma60_now
            slope = (ma60_now / ma60_prev - 1) * 100
            trend_s = 1.0 / (1.0 + math.exp(-(slope - 1.0) * 1.5))

            # 波动因子 (30%)
            rets = [(closes[i] / closes[i-1] - 1) * 100 for i in range(1, len(closes))]
            vol20 = np.std(rets[-20:]) * math.sqrt(252) if len(rets) >= 20 else 20
            vol_s = max(0, min(1, 1 - (vol20 - 15) / 25))

            # 量价确认 (30%)
            mv5 = sum(vols[-5:]) / 5
            mv20 = sum(vols[-20:]) / 20
            mp5 = sum(closes[-5:]) / 5
            mp20 = sum(closes[-20:]) / 20
            vr = mv5 / mv20 if mv20 > 0 else 1
            pr = mp5 / mp20
            confirm_s = 1.0 if (vr > 1 and pr > 1) or (vr < 1 and pr < 1) else 0.5

            score = trend_s * 0.40 + vol_s * 0.30 + confirm_s * 0.30
            label = '牛市' if score >= 0.7 else ('震荡' if score >= 0.4 else '熊市')
            return {'score': round(score, 2), 'label': label, 'details': {
                'trend': round(trend_s, 2), 'volatility': round(vol20, 1),
                'confirm': round(confirm_s, 2),
            }}
        except Exception as e:
            print(f"  ⚠️ 市场风险评估失败: {e}")
            return {'score': 1.0, 'label': '未知', 'details': {}}


class OrderManager:
    """仓位管理 + 风控检查"""

    def __init__(self, preload_industry: bool = True):
        self.exec = ExecutionEngine()
        self._industry_cache: dict = {}
        if preload_industry:
            self._load_industry_cache()

    def _load_industry_cache(self):
        """一次性加载全部股票行业映射，避免N次DB连接（从 tushare.db stock_basic）"""
        try:
            from core.db import get_tushare_db
            conn = get_tushare_db(read_only=True)
            rows = conn.execute("""
                SELECT ts_code, industry FROM stock_basic
            """).fetchall()
            conn.close()
            for r in rows:
                ts_code = str(r[0])
                stock_code = ts_code.replace('.SH', '').replace('.SZ', '')
                ind = str(r[1]) if r[1] else 'ZZZ'
                self._industry_cache[stock_code] = ind[:3] if len(ind) >= 3 else 'ZZZ'
        except Exception as e:
            print(f"  ⚠️ 行业缓存加载失败: {e}")

    def check_buy(self, account, signal, price: float, risk_coef: float = 1.0) -> Optional[dict]:
        """
        检查买入条件。
        返回: {code, shares, amount, reason} 或 None
        risk_coef: 市场风险系数 0-1, 直接缩放仓位
        """
        cfg = account.config
        if account.position_count >= cfg.get('max_positions', 5):
            return None
        if account.cash < cfg.get('min_cash_reserve', 10000):
            return None

        code = signal['code']
        score = signal.get(cfg.get('buy_score_col', 'reg20'), signal.get('fusion', 0))
        if score < cfg.get('buy_score_threshold', 5.0):
            return None

        dev120 = signal.get('dev120', 0)
        if dev120 > cfg.get('buy_max_upside_deviation', 25):
            return None

        # 同行业检查
        max_same = cfg.get('max_same_industry', 2)
        ind = self._get_industry(code)
        same_ind = sum(1 for p in account.positions if self._get_industry(p.code) == ind)
        if same_ind >= max_same:
            return None

        # 计算仓位 — 应用市场风险系数
        pct = self._calc_position_pct(score, cfg)
        max_amt = account.cash * pct * risk_coef
        shares = int(max_amt / price / 100) * 100
        if shares < 100:
            return None

        return {
            'code': code, 'name': signal.get('name', ''),
            'price': price, 'shares': shares,
            'score': score, 'method': f"{pct*100:.0f}%仓位",
        }

    def check_sells(self, account, signals_map, price_map) -> list:
        """
        检查所有持仓的卖出条件。
        返回: [{code, name, shares, pnl, reason}]
        """
        sell_orders = []

        for pos in list(account.positions):
            code = pos.code
            price = price_map.get(code)
            if not price:
                continue

            pnl = round((price / pos.avg_cost - 1) * 100, 2)
            peak = pos.peak_price or pos.avg_cost
            if price > peak:
                pos.peak_price = price
                peak = price
            drawdown = round((peak - price) / peak * 100, 2)

            sig = signals_map.get(code)
            use_col = account.config.get('buy_score_col', 'reg20')
            score = sig.get(use_col, sig.get('reg20', 0)) if sig else 0

            # 板块止损
            board_hard_loss = -15.0 if code.startswith(('300', '301', '688', '689')) else -12.0

            reasons = []

            # 1. 硬止损
            if pnl <= account.config.get('stop_loss_hard', -12.0):
                reasons.append(f"硬止损({pnl:+.1f}%)")

            # 2. 板块硬止损
            if pnl <= board_hard_loss and board_hard_loss < account.config.get('stop_loss_hard', -12.0):
                reasons.append(f"板块止损({pnl:+.1f}%)")

            # 3. 移动止盈
            if pnl > 5 and drawdown >= account.config.get('stop_loss_trailing', 8.0):
                reasons.append(f"高位回撤{drawdown:.1f}%")

            # 4. 目标止盈
            if pnl >= account.config.get('take_profit', 25.0):
                reasons.append(f"目标止盈({pnl:+.1f}%)")

            # 5. 信号转负
            if sig and score < account.config.get('signal_sell_threshold', -2.0):
                reasons.append(f"信号转负({score:.0f})")

            # 6. 年线破位
            if sig and sig.get('dev120', 0) < -15:
                reasons.append(f"年线破位({sig['dev120']:.0f}%)")

            if reasons:
                sell_orders.append({
                    'code': code, 'name': pos.name,
                    'price': price, 'shares': pos.shares,
                    'pnl': pnl, 'reason': '; '.join(reasons),
                })

        return sell_orders

    def _calc_position_pct(self, score: float, cfg: dict) -> float:
        """根据分数计算仓位比例"""
        ps = cfg.get('position_sizing', {})
        if score >= ps.get('score_high', {}).get('min', 12.0):
            return ps.get('score_high', {}).get('pct', 0.25)
        elif score >= ps.get('score_mid', {}).get('min', 8.0):
            return ps.get('score_mid', {}).get('pct', 0.15)
        else:
            return ps.get('score_low', {}).get('pct', 0.10)

    def _get_industry(self, code: str) -> str:
        """查询行业（取前3位）— 优先用内存缓存"""
        return self._industry_cache.get(code, 'ZZZ')

