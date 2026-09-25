#!/usr/bin/env python3
"""
多账户面板服务器 (8081)
只服务 dashboard.html 和必要的 API
"""
import os, sys, json, threading, time as _time, numpy as np
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
PORT = 8081

# ── 导入 core 库 ─────────────────────────────────────────
sys.path.insert(0, str(BASE))
from core.db import get_state_db, get_tushare_db, TUSHARE_DB_PATH
from core.hold_days import calc_holding_days as _trade_hold_days  # 交易日口径（2026-08-07 与后台决策统一）

# ── 价格源 ─────────────────────────────────────────────
# stock_basic 名称/行业进程级缓存（_stock_info_map 用；0915 加）
_STOCK_INFO_CACHE = {}
_STOCK_INFO_CACHE_TS = 0.0
_STOCK_INFO_TTL = 6 * 3600
_STOCK_INFO_LOCK = threading.Lock()

_PRICE_CACHE = {}
_PRICE_CACHE_TTL = 5.0  # 秒：前端 10s 轮询并发 6 个 API，5s 内共享一次实时价
_PRICE_CACHE_LOCK = threading.Lock()

# ── tushare.db 只读访问：重试 + 收盘价缓存（2026-09-17 修"锁冲突导致当日收益降级为 0"）──
# 背景：16:00 数据更新 / 16:10 TDX / 晚间链会独占 tushare.db，面板 duckdb.connect 抛
#   "Conflicting lock" → 当日收益 except 后静默留在 0.00%（2026-09-17 实测当天 71 次）。
# 修法：① 只读查询统一走 _duck_ro()（3 次重试 ≈5s）；
#      ② 当日收益所需的"近 3 个交易日 + 收盘价"落小缓存，彻底失败时用缓存兜底
#         （昨收日内恒定，用缓存只会略旧、不会算错）；
#      ③ 全部失败时保留上一次成功值，绝不再把降级值当 0 显示。
_PANEL_CACHE_PATH = BASE / '.cache' / 'panel_closes.json'
_LAST_GOOD_DAILY = {'ret': None, 'pct': None}


def _duck_ro(sql, params=None, retries=3, delay=1.0):
    """tushare.db 只读查询（带抖动重试）。全失败抛最后一个异常。"""
    import duckdb as _d
    import time as _t
    last = None
    for i in range(retries):
        con = None
        try:
            con = _d.connect(str(TUSHARE_DB_PATH), read_only=True)
            return con.execute(sql, params or []).fetchall()
        except Exception as e:
            last = e
            if i < retries - 1:
                _t.sleep(delay)
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass
    raise last


def _read_panel_cache():
    try:
        return json.loads(_PANEL_CACHE_PATH.read_text())
    except Exception:
        return None


def _write_panel_cache(dates, closes):
    try:
        _PANEL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PANEL_CACHE_PATH.with_suffix('.json.tmp')
        tmp.write_text(json.dumps({'dates': dates, 'closes': closes,
                                   'ts': datetime.now().isoformat(timespec='seconds')}))
        tmp.replace(_PANEL_CACHE_PATH)
    except Exception:
        pass


def _fetch_sina_prices(codes):
    """从新浪财经批量获取实时价（一次 HTTP 请求拉多只，替代逐只串行）
    新浪接口支持 list=sh600000,sz000001,... 逗号分隔，单请求返回全部。
    返回 {code: price}
    """
    import urllib.request
    import re
    if not codes:
        return {}
    # 去重保序，分批（新浪单请求不宜过长，每批 80 只）
    seen = set()
    uniq = [c for c in codes if not (c in seen or seen.add(c))]
    batch = 80
    result = {}
    for i in range(0, len(uniq), batch):
        chunk = uniq[i:i + batch]
        prefix = lambda c: 'sh' if c.startswith('6') else 'sz'
        qs = ','.join(f'{prefix(c)}{c}' for c in chunk)
        url = f'http://hq.sinajs.cn/list={qs}'
        req = urllib.request.Request(url, headers={
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        })
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            text = resp.read().decode('gbk')
            # 格式: var hq_str_sh600508="名称,今开,昨收,现价,最高,最低,..."
            for m in re.finditer(r'var hq_str_([a-z]{2})(\d+)="([^"]*)"', text):
                mkt, code, data = m.group(1), m.group(2), m.group(3).split(',')
                if len(data) > 3 and data[3]:
                    result[code] = float(data[3])  # 当前价
        except Exception:
            continue
    return result


def _fetch_sina_price(code):
    """从新浪财经获取实时价（单只，兼容旧调用）"""
    return _fetch_sina_prices([code]).get(code)


def _get_prices(codes, source='close'):
    """获取股票最新价格
    source='close': 从 tushare.db 取最近收盘价
    source='realtime': 从新浪取实时价（批量接口 + 5s 缓存）
    返回 {code: price}
    """
    result = {}
    if source == 'realtime':
        codes = list(dict.fromkeys(c for c in codes if c))  # 去重保序
        if not codes:
            return result
        now = datetime.now().timestamp()
        with _PRICE_CACHE_LOCK:
            hit = {c: v for c, v in _PRICE_CACHE.items() if now - v[1] < _PRICE_CACHE_TTL}
            miss = [c for c in codes if c not in hit]
        result.update({c: v[0] for c, v in hit.items()})
        if miss:
            fresh = _fetch_sina_prices(miss)
            with _PRICE_CACHE_LOCK:
                for c, p in fresh.items():
                    _PRICE_CACHE[c] = (p, now)
            result.update(fresh)
        return result

    # 默认：从 tushare.db 取最近收盘价（2026-09-17：改走 _duck_ro 重试；仍失败用面板缓存兜底）
    try:
        for c in codes:
            full = f"{c}.SH" if c.startswith('6') else f"{c}.SZ"
            _rows = _duck_ro(
                "SELECT close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", [full])
            if _rows and _rows[0] and _rows[0][0]:
                result[c] = float(_rows[0][0])
    except Exception as _e:
        _c = _read_panel_cache() or {}
        _miss = [c for c in codes if c not in result]
        for c in _miss:
            full = f"{c}.SH" if c.startswith('6') else f"{c}.SZ"
            _dm = (_c.get('closes') or {}).get(full) or {}
            if _dm:
                try:
                    result[c] = float(_dm[max(_dm)])
                except Exception:
                    pass
        print(f"[dashboard] 收盘价查询失败，用缓存兜底 {len(_miss)} 只: {_e}", flush=True)
    return result

class DashboardHandler(BaseHTTPRequestHandler):
    def _html(self, text):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')  # 2026-08-06：防浏览器缓存旧 dashboard.html
        self.end_headers()
        self.wfile.write(text.encode('utf-8'))
    
    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')  # 2026-08-06：防浏览器缓存旧 API 数据
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        # 价格源：?source=realtime  → 新浪实时价; 默认 tushare 收盘价
        price_source = (params.get('source') or ['close'])[0]
        if price_source not in ('close', 'realtime'):
            price_source = 'close'
        self.price_source = price_source
        
        # 服务 dashboard.html
        if path == '/' or path == '/dashboard.html':
            dashboard_path = BASE / 'static' / 'dashboard.html'
            if dashboard_path.exists():
                self._html(dashboard_path.read_text(encoding='utf-8'))
            else:
                self._json({"error": "dashboard.html not found"}, 404)
            return
        
        # API: 仪表盘数据
        if path == '/api/dashboard':
            self._handle_dashboard()
            return
        
        # API: 持仓数据
        if path == '/api/positions':
            self._handle_positions()
            return
        
        # API: 信号数据
        if path == '/api/signals':
            self._handle_signals()
            return
        
        # API: 交易记录
        if path == '/api/trades':
            self._handle_trades()
            return

        # API: TDX 信号策略统计（2026-08-08）
        if path == '/api/tdx-stats':
            self._handle_tdx_stats()
            return
        
        # API: IC 数据
        if path == '/api/ic':
            self._handle_ic()
            return
        
        # API: 个股分析
        if path.startswith('/api/stock/') and path.endswith('/analyze'):
            code = path.split('/')[3]
            self._handle_analyze(code)
            return
        
        # API: ETF 分析
        if path.startswith('/api/etf/') and path.endswith('/analyze'):
            code = path.split('/')[3]
            self._handle_etf_analyze(code)
            return
        
        # API: ETF 全市场评分排名
        if path == '/api/etf-rank':
            self._handle_etf_rank()
            return
        
        # API: 定时任务列表
        if path == '/api/cron-jobs':
            self._handle_cron_jobs()
            return
        
        # API: ETF 分类列表
        if path == '/api/etf-list':
            self._handle_etf_list()
            return
        # API: ETF 评分列表
        if path == '/api/etf-scores':
            self._handle_etf_scores()
        if path == '/api/fusion-3f-watchlist':
            self._handle_fusion3f_watchlist()
            return
        if path == '/api/cmmr-watchlist':
            self._handle_cmmr_watchlist()
            return
        if path == '/api/cmmr-fusion-watchlist':
            self._handle_cmmr_fusion_watchlist()
            return
        if path == '/api/fusion-center-watchlist':
            self._handle_fusion_center_watchlist()
            return
        if path == '/api/fusion-dual-watchlist':
            self._handle_fusion_dual_watchlist()
            return
        if path == '/api/center-dual-watchlist':
            self._handle_center_dual_watchlist()
            return
        if path == '/api/opinions':
            self._handle_opinions()
            return
        if path == '/api/shadow':
            self._handle_shadow()
            return
        if path.startswith('/api/quote'):
            self._handle_quote(parse_qs(urlparse(self.path).query))
            return
        
        self._json({"error": "not found"}, 404)
    
    def _handle_dashboard(self):
        """返回账户总览"""
        conn = get_state_db()
        
        # 读取账户余额
        acc_row = conn.execute("SELECT account_id, account_name, initial_capital, cash_balance, total_value FROM account_balance WHERE account_id='main'").fetchone()
        
        if not acc_row:
            conn.close()
            self._json({"accounts": {"main": {"total_nav": 1000000, "total_pnl": 0, "total_return": 0, "cash": 1000000, "position_value": 0}}, "positions": [], "signals": []})
            return
        
        account_id, account_name, initial_capital, cash_balance, total_value = acc_row
        
        # 读取持仓
        pos_rows = conn.execute("SELECT code, shares, avg_cost, buy_date, latest_price, name FROM holdings").fetchall()
        codes = [r[0] for r in pos_rows]
        _latest_map = _get_prices(codes, source=self.price_source)
        
        positions = []
        for r in pos_rows:
            code, shares, avg_cost, buy_date, latest_price, name = r
            shares = shares or 0
            avg_cost = avg_cost or 0
            latest_price = _latest_map.get(code) or latest_price or avg_cost
            # 计算盈亏
            pnl = (latest_price - avg_cost) * shares
            pnl_pct = (latest_price / avg_cost - 1) * 100 if avg_cost > 0 else 0
            positions.append({
                'code': code,
                'shares': shares,
                'avg_cost': round(avg_cost, 4),
                'latest_price': round(latest_price, 4),
                'buy_date': str(buy_date) if buy_date else '-',
                'name': name or code,
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2)
            })
        
        # 计算净值
        # 持仓市值用修正后的最新价
        pos_val = 0
        for r in pos_rows:
            code, shares = r[0], r[1] or 0
            avg_cost = r[2] or 0
            holdings_lp = r[4] or avg_cost
            lp = _latest_map.get(code) or holdings_lp
            pos_val += lp * shares
        
        init = initial_capital or 1000000
        cash = cash_balance or 0
        nav = cash + pos_val
        total_pnl = nav - init
        total_return = total_pnl / init * 100 if init else 0

        # 主账户当日收益（2026-08-25 修口径：三种模式语义明确）
        #  有今收（收盘后）：今日收盘资产 vs 昨日收盘资产
        #  实时价（盘中）  ：今日实时资产 vs 最近收盘日资产（当日实时收益）
        #  收盘价（盘中）  ：最近收盘日资产 vs 前收盘日资产（昨日收盘的当日收益）
        # 昨日持仓/现金用 trade_log 反推（昨日持仓 = 今日持仓 − 今日买入 + 今日卖出，
        # 今日全清仓的股票从卖出补回；昨日现金 = 今日现金 − 卖出收入 + 买入支出）
        daily_ret = 0.0
        daily_ret_pct = 0.0
        try:
            import duckdb as _duckdb  # noqa: F401  （保留：_closest_close 内用到 _duck_ro 前的兼容）
            _cache = None
            try:
                _dates = [r[0] for r in _duck_ro(
                    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 3")]
            except Exception as _e0:
                _cache = _read_panel_cache()
                if not _cache or not _cache.get('dates'):
                    raise
                _dates = _cache['dates']
                print(f"[dashboard] tushare 锁占用，当日收益改用缓存兜底（缓存 {_cache.get('ts')}）: {_e0}",
                      flush=True)
            _today = datetime.now().strftime('%Y%m%d')
            _has_today_close = bool(_dates) and _dates[0] == _today
            _last_d = _dates[0] if _dates else None
            # 最近收盘日 = 无今收时 dates[0]（如盘中看 8/24），有今收时 dates[1]（昨日）
            _prev_d = _dates[1] if (_has_today_close and len(_dates) > 1) else (_dates[0] if _dates else None)
            # 第二层反推估值日（_prev_d 的前一交易日）：有今收 dates=[今,昨,前]→dates[2]；
            # 无今收 dates=[昨,前,前前]→dates[1]
            _prev2_d = _dates[2] if (_has_today_close and len(_dates) > 2) else (_dates[1] if len(_dates) > 1 else _prev_d)
            _closes = {}
            if _dates:
                if _cache:
                    for _ts, _dmap in (_cache.get('closes') or {}).items():
                        _closes[_ts] = {_k: float(_v) for _k, _v in _dmap.items()}
                else:
                    try:
                        for _d in _dates:
                            for _ts, _c in _duck_ro(
                                    "SELECT ts_code, close FROM daily WHERE trade_date=?", [_d]):
                                _closes.setdefault(_ts, {})[_d] = float(_c)
                        _write_panel_cache(list(_dates), _closes)
                    except Exception as _e2:
                        _cache = _read_panel_cache()
                        if not _cache or not _cache.get('closes'):
                            raise
                        _dates = _cache.get('dates') or _dates
                        for _ts, _dmap in _cache['closes'].items():
                            _closes[_ts] = {_k: float(_v) for _k, _v in _dmap.items()}
                        print(f"[dashboard] 收盘价查询失败，当日收益用缓存兜底: {_e2}", flush=True)
            # 反推前一日资产：给定某日持仓/现金/当日成交，反推前一交易日持仓/现金并用其收盘价估值。
            # _iso_d 用裸码 YYYYMMDD；trade_log 用 REPLACE 归一化（横线/裸码混存坑）。
            def _closest_close(_full0, _day):
                """≤_day 的最近收盘价（2026-09-04 修复：停牌股无当日行时用最后收盘价估值，
                市值不归零——原 _closes 精确日匹配 miss → 直接跳过/成本兜底，与报告口径打架）。
                链：_closes 3 日窗口 → duckdb 直查任意回溯（长期停牌）。查不到返回 0。"""
                _dmap = _closes.get(_full0) or {}
                _ok = [d for d in _dmap if d <= _day]
                if _ok:
                    return _dmap[max(_ok)]
                try:
                    _r2 = _duck_ro(
                        "SELECT close FROM daily WHERE ts_code=? AND trade_date<=? "
                        "ORDER BY trade_date DESC LIMIT 1", (_full0, _day))
                    return float(_r2[0][0]) if _r2 and _r2[0] and _r2[0][0] else 0.0
                except Exception:
                    _cm = ((_cache or _read_panel_cache()) or {}).get('closes', {}).get(_full0) or {}
                    _ok2 = [_d for _d in _cm if _d <= _day]
                    return float(_cm[max(_ok2)]) if _ok2 else 0.0

            def _reverse_day(_pos_rows, _cash_now, _iso_d, _prev_iso):
                _b, _s = {}, {}
                _sell, _buy = 0.0, 0.0
                # 2026-09-04 除权还原：_iso_d 当日该股除权时（盘前已调账），今日持仓=送转后股数、
                # 现金已含股息 → 反推昨日持仓须 ÷factor、昨日现金须 −净息（防除权日收益假亏）
                _ca_map = {}
                try:
                    for _cr in conn.execute(
                            "SELECT code, factor, cash_div, tax_rate FROM ca_adjustments "
                            "WHERE ex_date=? AND account='main'",
                            (str(_iso_d),)).fetchall():
                        _ca_map[_cr[0]] = (float(_cr[1] or 1), float(_cr[2] or 0), float(_cr[3] or 0))
                except Exception:
                    pass
                for _r in conn.execute(
                        "SELECT code, direction, quantity, amount FROM trade_log "
                        "WHERE REPLACE(trade_date,'-','')=? AND (strategy='main' OR strategy IS NULL)",
                        (_iso_d,)).fetchall():
                    _c0, _dir0, _q0, _a0 = _r[0], _r[1], _r[2] or 0, _r[3] or 0
                    if _dir0 == 'BUY':
                        _b[_c0] = _b.get(_c0, 0) + _q0
                        _buy += _a0
                    elif _dir0 == 'SELL':
                        _s[_c0] = _s.get(_c0, 0) + _q0
                        _sell += _a0
                _pos_prev = {}
                for _r in _pos_rows:
                    _c0, _sh0 = _r[0], _r[1] or 0
                    _ps = _sh0 - _b.get(_c0, 0) + _s.get(_c0, 0)
                    if _c0 in _ca_map:
                        _f = _ca_map[_c0][0]
                        if _f and _f != 1.0:
                            _ps = int(round(_ps / _f))
                    if _ps > 0:
                        _pos_prev[_c0] = _ps
                for _c0, _sq in _s.items():
                    if _c0 not in _pos_prev and _c0 not in _b:
                        _pos_prev[_c0] = _sq
                        if _c0 in _ca_map:
                            _f = _ca_map[_c0][0]
                            if _f and _f != 1.0:
                                _pos_prev[_c0] = int(round(_sq / _f))  # 卖出的是送转后股数
                _cash_prev = _cash_now - _sell + _buy
                for _c0, (_f, _cd, _tr) in _ca_map.items():
                    if _c0 in _pos_prev:
                        _cash_prev -= _pos_prev[_c0] * _cd * (1 - _tr)  # 股息不属于昨日现金
                _asset_prev = _cash_prev
                for _c0, _ys in _pos_prev.items():
                    _full0 = f"{_c0}.SH" if _c0.startswith('6') else f"{_c0}.SZ"
                    _p0 = _closest_close(_full0, _prev_iso)
                    if _p0:
                        _asset_prev += _ys * _p0
                return _asset_prev, _cash_prev, _pos_prev
            _today_iso = f"{_today[:4]}-{_today[4:6]}-{_today[6:8]}"
            _asset_prev, _cash_prev, _pos_prev = _reverse_day(pos_rows, cash, _today, _prev_d)
            if _has_today_close:
                # 有今收：今日（今收）vs 昨日
                _cur_asset = cash
                for _r in pos_rows:
                    _c0, _sh0 = _r[0], _r[1] or 0
                    if _sh0 <= 0:
                        continue
                    _full0 = f"{_c0}.SH" if _c0.startswith('6') else f"{_c0}.SZ"
                    # 2026-09-04：停牌/新股用最近收盘兜底（avg_cost 仅作无任何历史价时的最终兜底）
                    _cur = _closest_close(_full0, _last_d) or _r[2] or 0
                    _cur_asset += _sh0 * _cur
                daily_ret = _cur_asset - _asset_prev
                _ret_base = _asset_prev
            elif self.price_source == 'realtime':
                # 盘中实时价：今日实时 vs 最近收盘日
                _cur_asset = cash
                for _r in pos_rows:
                    _c0, _sh0 = _r[0], _r[1] or 0
                    if _sh0 <= 0:
                        continue
                    _full0 = f"{_c0}.SH" if _c0.startswith('6') else f"{_c0}.SZ"
                    # 2026-09-04：实时价 → 最近收盘（停牌无实时价时）→ avg_cost 最终兜底
                    _cur = _latest_map.get(_c0) or _closest_close(_full0, _last_d) or _r[2] or 0
                    _cur_asset += _sh0 * _cur
                daily_ret = _cur_asset - _asset_prev
                _ret_base = _asset_prev
            else:
                # 收盘价模式（盘中）：最近收盘日 vs 前收盘日（显示昨日收盘的当日收益）
                _asset_prev2, _, _ = _reverse_day(
                    [(_c, _sh) for _c, _sh in _pos_prev.items()], _cash_prev, _prev_d, _prev2_d)
                daily_ret = _asset_prev - _asset_prev2
                _ret_base = _asset_prev2
            if _ret_base > 0:
                daily_ret_pct = daily_ret / _ret_base * 100
        except Exception as _e:
            # 2026-09-17：绝不把降级值当结果——保留上一次成功值（进程内存），日志标 degraded
            if _LAST_GOOD_DAILY['ret'] is not None:
                daily_ret, daily_ret_pct = _LAST_GOOD_DAILY['ret'], _LAST_GOOD_DAILY['pct']
                print(f"[dashboard] 当日收益计算失败（保留上次值 {daily_ret:,.2f} 元 / "
                      f"{daily_ret_pct:+.4f}%）: {_e}", flush=True)
            else:
                print(f"[dashboard] 当日收益计算失败且无上次值（显示 0 属降级，请查 tushare 锁）: {_e}",
                      flush=True)
        else:
            _LAST_GOOD_DAILY['ret'], _LAST_GOOD_DAILY['pct'] = daily_ret, daily_ret_pct
        
        conn.close()  # 2026-08-24：当日收益计算依赖 conn 查 trade_log，close 必须在其后
        
        # 取最新信号
        sdb = get_state_db()
        sig_rows = sdb.execute("SELECT date, stock_code, stock_name, fusion_score, final_score, reg20, reg40, reg10, industry, deviation120 FROM signal_history WHERE stock_name NOT LIKE '%ST%' ORDER BY REPLACE(date, '-', '') DESC, final_score DESC LIMIT 30").fetchall()
        signals = [{'date': str(r[0]), 'stock_code': r[1], 'stock_name': r[2], 'fusion_score': r[3] or 0, 'final_score': r[4] or 0, 'reg20': r[5], 'reg40': r[6], 'reg10': r[7], 'industry': r[8] or '', 'deviation120': r[9] or 0} for r in sig_rows]

        # 策略独立模拟账户（fusion3f/cmmr/cmmr_fusion）—— 从 strategy_accounts NAV 表读
        strat_accounts = {}
        # 1) 读 sim_accounts JSON 持仓（裸代码）
        import json as _json
        from core.unified_account import ACCOUNTS_DIR as _ACCOUNTS_DIR
        strat_raw = {}
        strat_codes = []
        for _aid in ('fusion3f', 'cmmr', 'cmmr_fusion', 'fusion_center', 'fusion_dual', 'center_dual', 'agent_auto', 'reg10_solo', 'cmmr_clf'):
            _p = _ACCOUNTS_DIR / f'{_aid}.json'
            if not _p.exists():
                continue
            try:
                _data = _json.loads(_p.read_text(encoding='utf-8'))
                _pos = [{'code': x.get('code'), 'shares': x.get('shares', 0),
                         'avg_cost': x.get('avg_cost', 0), 'name': x.get('name', ''),
                         'buy_date': x.get('buy_date', '')}
                        for x in _data.get('positions', []) if x.get('code')]
                strat_raw[_aid] = _pos
                strat_codes += [x['code'] for x in _pos]
            except Exception:
                pass
        strat_prices = _get_prices(strat_codes, source=self.price_source) if strat_codes else {}

        # 补股票名称（sim_accounts JSON 里 name 可能为空）
        strat_names = {}
        if strat_codes:
            try:
                import duckdb
                _tdb = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
                for _c in strat_codes:
                    _full = f'{_c}.SH' if _c.startswith('6') else f'{_c}.SZ'
                    _r = _tdb.execute(
                        'SELECT name FROM stock_basic WHERE ts_code=?', [_full]).fetchone()
                    if _r and _r[0]:
                        strat_names[_c] = _r[0]
                _tdb.close()
            except Exception:
                pass

        # 2) NAV + 持仓组装
        for aid, label in [('fusion3f', '三因子融合(已销户)'), ('cmmr', 'CMMR独立'), ('cmmr_fusion', 'CMMR+融合'), ('fusion_center', '中枢版Top10'), ('fusion_dual', '三因子+三模型(已销户)'), ('center_dual', '中枢版+三模型'), ('agent_auto', 'Agent全权'), ('reg10_solo', '10d独立'), ('cmmr_clf', 'CMMR+clf门票')]:
            try:
                r = sdb.execute("""
                    SELECT date, nav, daily_ret, market_ret, n_pos, cash, pos_value
                    FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 1
                """, (aid,)).fetchone()
                base = 1000000.0  # 策略账户初始资金，累计收益从初始算
                pos_list = []
                for x in strat_raw.get(aid, []):
                    lp = strat_prices.get(x['code']) or x['avg_cost'] or 0
                    pnl = (lp - x['avg_cost']) * x['shares']
                    pnl_pct = (lp / x['avg_cost'] - 1) * 100 if x['avg_cost'] else 0
                    pos_list.append({
                        'code': x['code'], 'name': x['name'] or strat_names.get(x['code']) or x['code'],
                        'shares': x['shares'], 'avg_cost': round(x['avg_cost'], 4),
                        'latest_price': round(lp, 4), 'pnl': round(pnl, 2),
                        'pnl_pct': round(pnl_pct, 2),
                        'buy_date': str(x.get('buy_date', '')) or '-',
                        'hold_days': self._hold_days(x.get('buy_date'))})
                if not r:
                    # 尚无交易记录：显示初始状态（空仓 100 万），等首个交易日建仓
                    strat_accounts[aid] = {
                        'name': label, 'date': '-',
                        'total_nav': base, 'total_return': 0.0,
                        'daily_ret': 0.0, 'market_ret': 0.0,
                        'n_pos': len(pos_list), 'cash': base,
                        'position_value': 0.0, 'positions': pos_list,
                    }
                    continue
                strat_accounts[aid] = {
                    'name': label,
                    'date': str(r[0]),
                    'total_nav': round(r[1], 2),
                    'total_return': round((r[1] / base - 1) * 100, 2) if base else 0.0,
                    'daily_ret': round(r[2] or 0, 4),
                    'market_ret': round(r[3] or 0, 4),
                    'n_pos': r[4] or 0,
                    'cash': round(r[5] or 0, 2),
                    'position_value': round(r[6] or 0, 2),
                    'positions': pos_list,
                }
            except Exception:
                pass
        sdb.close()
        
        accounts = {
            "main": {
                "total_nav": round(nav, 2),
                "total_pnl": round(total_pnl, 2),
                "total_return": round(total_return, 2),
                "cash": round(cash_balance, 2),
                "position_value": round(pos_val, 2),
                "daily_ret": round(daily_ret, 2),
                "daily_ret_pct": round(daily_ret_pct, 2),
            }
        }
        accounts.update(strat_accounts)
        self._json({
            "accounts": accounts,
            "positions": positions,
            "nav_history": [],
            "signals": signals,
        })
    
    def _hold_days(self, buy_date):
        """持仓天数（交易日口径，2026-08-07 与后台决策统一；
        原自然日口径在周末/节假日会多算，误导卖出规则判断）
        兼容 YYYY-MM-DD / YYYYMMDD，异常返回 None"""
        try:
            return _trade_hold_days(buy_date)
        except Exception:
            return None

    def _handle_quote(self, query):
        """只读行情接口（2026-08-06，供 family profile 小rayray 查询）
        /api/quote?code=600508   → 股票实时价
        /api/quote?code=510300   → 基金净值（fund_daily 最新）
        返回: {code, name, price, chg_pct, source}
        """
        code = (query.get('code') or [''])[0].strip()
        if not code:
            self._json({"error": "missing code"}, 400)
            return
        try:
            import duckdb
            # 名称查询：先股票后基金
            name = ''
            source = 'sina'
            try:
                tdb = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
                r = tdb.execute(
                    "SELECT name FROM stock_basic WHERE ts_code=?", 
                    [f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"]).fetchone()
                if r and r[0]:
                    name = r[0]
                if not name:
                    r2 = tdb.execute("SELECT name FROM fund_basic WHERE ts_code=?", [f"{code}.SH" if code.startswith('5') else f"{code}.SZ"]).fetchone()
                    if r2 and r2[0]:
                        name = r2[0]
                        source = 'fund'
                tdb.close()
            except Exception:
                pass

            if source == 'fund':
                # 基金净值（fund_daily 最新）
                try:
                    tdb = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
                    ts = f"{code}.SH" if code.startswith('5') else f"{code}.SZ"
                    r = tdb.execute(
                        "SELECT trade_date, close, pct_chg FROM fund_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
                        [ts]).fetchone()
                    tdb.close()
                    if r:
                        self._json({"code": code, "name": name or code, "price": float(r[1]),
                                    "nav_date": str(r[0]), "chg_pct": float(r[2]) if r[2] is not None else None,
                                    "source": "fund_daily"})
                        return
                except Exception:
                    pass
                self._json({"code": code, "name": name or code, "price": None, "chg_pct": None,
                            "source": "fund", "note": "fund_daily 无数据"})
                return

            # 股票实时价（sina）
            from core.prices import fetch_price_live
            px, chg = fetch_price_live(code)
            self._json({"code": code, "name": name or code, "price": round(px, 3) if px else None,
                        "chg_pct": round(chg, 2) if px else None, "source": "sina"})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _stock_info_map(self, codes):
        """从 tushare.db 批量取 {裸码: (名称, 行业)}（v2: stock_basic 副本已删, 读方改读 tushare）
        v3(2026-09-15): stock_basic 进程级缓存。此前每次调用都开 duckdb 只读连接，
        update_etf 等写入任务持锁时 read_lock 等 10s 超时 → except 吞掉 → 名称列退回代码、行业空白、
        且每个页面白等 10 秒（CMMR/CMMR+ 页 0915 事故）。缓存命中零锁竞争，6h 后台刷一次。"""
        global _STOCK_INFO_CACHE, _STOCK_INFO_CACHE_TS
        info = dict(_STOCK_INFO_CACHE)  # 快照（可能为空/旧，兜底用）
        stale = (_time.time() - _STOCK_INFO_CACHE_TS) > _STOCK_INFO_TTL
        if codes and stale and _STOCK_INFO_LOCK.acquire(blocking=False):
            # 只有缓存过期且无人抢着刷时才开真连接；锁竞争失败照旧用缓存兜底
            try:
                fresh = {}
                tdb = get_tushare_db(read_only=True)
                for tc, nm, ind in tdb.execute(
                        "SELECT ts_code, name, industry FROM stock_basic").fetchall():
                    fresh[str(tc).replace('.', '')[:6]] = (nm or '', ind or '')
                tdb.close()
                if fresh:
                    _STOCK_INFO_CACHE = fresh
                    _STOCK_INFO_CACHE_TS = _time.time()
                info = dict(_STOCK_INFO_CACHE)
            except Exception:
                # 读不到用旧缓存，且 60s 内不再尝试（写入持锁时勿每请求白等 10s read_lock 超时）
                _STOCK_INFO_CACHE_TS = _time.time() - _STOCK_INFO_TTL + 60
            finally:
                _STOCK_INFO_LOCK.release()
        if not codes:
            return info
        return {c: info.get(c, ('', '')) for c in map(str, codes)}

    def _handle_signals(self):
        """返回观察名单数据（watchlist 表）"""
        conn = get_state_db()
        # 从 watchlist 表读取最新一天的观察名单, join signal_history; 名称/行业从 tushare.db 补（v2）
        rows = conn.execute("""
            SELECT w.ts_code, w.score, w.scan_date,
                   sh.reg20, sh.reg40, sh.reg10, sh.deviation120,
                   w.entry_low, w.entry_high, w.target_price, w.stop_loss
            FROM watchlist w
            LEFT JOIN signal_history sh ON w.ts_code = sh.stock_code
                AND REPLACE(sh.date, '-', '') = (SELECT REPLACE(date, '-', '') FROM signal_history ORDER BY REPLACE(date, '-', '') DESC LIMIT 1)
            WHERE w.scan_date = (SELECT scan_date FROM watchlist WHERE scan_date IS NOT NULL ORDER BY REPLACE(scan_date, '-', '') DESC LIMIT 1)
              AND w.score >= 70
            ORDER BY w.score DESC
            LIMIT 50
        """).fetchall()
        conn.close()
        
        info = self._stock_info_map({str(r[0]) for r in rows})
        signals = []
        for r in rows:
            # watchlist 表字段：ts_code, score, scan_date, status + sh.reg20, sh.reg40, sh.reg10, sh.deviation120 + bollinger
            signals.append({
                'date': str(r[2]),           # scan_date
                'stock_code': r[0],          # ts_code
                'stock_name': info.get(str(r[0]), ('', ''))[0] or r[0],  # tushare 名称, ts_code 兜底
                'fusion_score': r[1] or 0,   # score
                'final_score': None,
                'reg20': r[3] or 0,
                'reg40': r[4] or 0,
                'reg10': r[5] or 0,
                'industry': info.get(str(r[0]), ('', ''))[1],
                'deviation120': r[6] or 0,
                'entry_low': r[7] or 0,
                'entry_high': r[8] or 0,
                'target_price': r[9] or 0,
                'stop_loss': r[10] or 0,
            })
        
        self._json({"signals": signals})
    
    def _handle_positions(self):
        """返回持仓数据（含实时价格和PnL）"""
        conn = get_state_db()
        rows = conn.execute("SELECT code, shares, avg_cost, buy_date, latest_price, name FROM holdings").fetchall()
        conn.close()
        codes = [r[0] for r in rows]
        latest_prices = _get_prices(codes, source=self.price_source)
        
        positions = []
        for r in rows:
            code, shares, avg_cost, buy_date, latest_price, name = r
            lp = latest_prices.get(code) or latest_price or avg_cost
            shares = shares or 0
            avg_cost = avg_cost or 0
            pnl = (lp - avg_cost) * shares
            pnl_pct = (lp / avg_cost - 1) * 100 if avg_cost > 0 else 0
            positions.append({
                'code': code,
                'shares': shares,
                'avg_cost': round(avg_cost, 4),
                'latest_price': round(lp, 4),
                'buy_date': str(buy_date) if buy_date else '-',
                'hold_days': self._hold_days(buy_date),
                'name': name or code,
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2)
            })
        
        self._json({"positions": positions})
    
    def _handle_trades(self):
        """返回交易记录"""
        conn = get_state_db()
        rows = conn.execute("SELECT trade_date, code, name, direction, price, quantity, amount, strategy, signal_score, trade_time FROM trade_log ORDER BY trade_date DESC, id DESC LIMIT 100").fetchall()
        conn.close()
        
        # 策略账户 strategy → 显示名映射（主账户 strategy 为空 → main）
        strat_names = {'fusion3f': '三因子融合(已销户)', 'cmmr': 'CMMR独立', 'cmmr_fusion': 'CMMR+融合', 'fusion_center': '中枢版Top10', 'fusion_dual': '三因子+三模型(已销户)', 'center_dual': '中枢版+三模型', 'agent_auto': 'Agent全权', 'reg10_solo': '10d独立', 'cmmr_clf': 'CMMR+clf门票'}
        trades = []
        for r in rows:
            strat = r[7] or ''
            trades.append({
                'date': str(r[0]),           # trade_date
                'trade_time': str(r[9] or ''),  # trade_time HH:MM:SS
                'account_id': strat_names.get(strat, 'main'),   # 策略账户显示中文名，主账户 main
                'stock_code': r[1],          # code
                'stock_name': r[2],          # name
                'direction': r[3],           # direction
                'price': r[4],               # price
                'shares': r[5],              # quantity
                'amount': r[6],              # amount
                'strategy': strat,           # strategy
                'signal_score': r[8]         # signal_score
            })
        
        self._json({"trades": trades})
    
    def _handle_tdx_stats(self):
        """TDX 信号策略统计（2026-08-08 用户要求: 策略交易全部统计）"""
        import duckdb
        conn = get_state_db()
        rows = conn.execute("SELECT log_date, signal_date, code, signal_type, action, price, account FROM tdx_signal_log ORDER BY id DESC LIMIT 500").fetchall()
        conn.close()
        if not rows:
            self._json({"summary": [], "by_account": [], "recent": [], "note": "自 2026-08-08 起记录, 暂无数据"})
            return

        # 次日收益回填（signal_date 收盘 → 次日收盘）
        tdb = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
        tds = [str(r[0]) for r in tdb.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '2026-02-01' ORDER BY trade_date").fetchall()]
        nx = {d: tds[i+1] for i, d in enumerate(tds[:-1])}
        px = {}
        for d, tc, cl in tdb.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '2026-02-01'").fetchall():
            px.setdefault(str(d), {})[tc] = float(cl)
        tdb.close()

        TYPE_NAMES = {'excluded_tail': '排除-出货急拉', 'excluded_entrap': '排除-诱多组合',
                      'low_absorb': '低吸确认', 'wash': '低吸-资金洗盘', 'normal_buy': '普通买入'}
        ACCT_NAMES = {'main': '主账户', 'fusion3f': '三因子融合(已销户)', 'cmmr': 'CMMR独立',
                      'cmmr_fusion': 'CMMR+融合', 'fusion_center': '中枢版Top10', 'fusion_dual': '三因子+三模型(已销户)', 'center_dual': '中枢版+三模型', 'agent_auto': 'Agent全权', 'reg10_solo': '10d独立', 'cmmr_clf': 'CMMR+clf门票'}
        entries = []
        for r in rows:
            sig_date = str(r[1])
            nxt = nx.get(sig_date)
            ts = f"{r[2]}.SH" if str(r[2]).startswith(('6', '68', '9')) else f"{r[2]}.SZ"
            ret = None
            if nxt:
                c0, c1 = px.get(sig_date, {}).get(ts), px.get(nxt, {}).get(ts)
                if c0 and c1 and c0 > 0:
                    ret = round((c1 / c0 - 1) * 100, 2)
            entries.append({'log_date': str(r[0]), 'signal_date': sig_date, 'code': r[2],
                            'type': TYPE_NAMES.get(r[3], r[3]), 'type_key': r[3],
                            'action': r[4], 'account': ACCT_NAMES.get(r[6], r[6] or '主账户'),
                            'next_ret': ret})

        agg = {}
        for e in entries:
            k = e['type_key']
            agg.setdefault(k, {'n': 0, 'rets': []})
            agg[k]['n'] += 1
            if e['next_ret'] is not None:
                agg[k]['rets'].append(e['next_ret'])
        summary = [{'type': TYPE_NAMES.get(k, k), 'n': v['n'],
                    'next_mean': round(float(np.mean(v['rets'])), 3) if v['rets'] else None,
                    'next_med': round(float(np.median(v['rets'])), 3) if v['rets'] else None}
                   for k, v in agg.items()]

        acct = {}
        for e in entries:
            a = e['account']
            acct.setdefault(a, {'n': 0, 'rets': []})
            acct[a]['n'] += 1
            if e['next_ret'] is not None:
                acct[a]['rets'].append(e['next_ret'])
        by_account = [{'account': k, 'n': v['n'],
                       'next_mean': round(float(np.mean(v['rets'])), 3) if v['rets'] else None}
                      for k, v in acct.items()]

        self._json({"summary": summary, "by_account": by_account, "recent": entries[:50]})

    def _handle_ic(self):
        """返回 IC 统计数据（因子 IC + 模型 IC）"""
        conn = get_state_db()
        
        # 1. 因子 IC（从 factor_ic_roll 表）
        rows = conn.execute("""
            SELECT f1.factor_name, f1.mean_ic, f1.icir, f1.win_rate,
                   f1.max_ic, f1.min_ic, f1.n_days, f1.as_of_date,
                   f1.mean_ret, f1.median_ret
            FROM factor_ic_roll f1
            WHERE f1.window = 20
            AND f1.as_of_date = (SELECT MAX(f2.as_of_date) FROM factor_ic_roll f2 WHERE f2.factor_name = f1.factor_name AND f2.window = 20)
            ORDER BY f1.factor_name
        """).fetchall()
        
        ic_data = []
        for r in rows:
            # fusion 行（fusion_3f_score/强买）是单日 IC：icir/max_ic/min_ic 无意义
            # （表内 NULL 或占位 0），一律保留 None 让前端显示 '-'（2026-08-08 修）
            is_fusion = str(r[0]).startswith('fusion')
            ic_data.append({
                'factor_name': r[0],
                'ic_mean': r[1] or 0,
                'icir': None if is_fusion else r[2],
                'win_rate': r[3] or 0,  # 表内统一小数（0-1）
                'max_ic': None if is_fusion else r[4],
                'min_ic': None if is_fusion else r[5],
                'n_days': int(r[6] or 0),
                'as_of_date': str(r[7] or '')[:10],
                'mean_ret': round(r[8], 4) if r[8] is not None else None,
                'median_ret': round(r[9], 4) if r[9] is not None else None
            })
        
        # 加算三因子融合滚动统计（所有历史日IC；胜率取历史信号胜率均值）
        fusion_roll = {'fusion_3f_score': {}, 'fusion_3f_强买': {}}
        for fname in ['fusion_3f_score', 'fusion_3f_强买']:
            hist = conn.execute("""
                SELECT as_of_date, mean_ic, win_rate FROM factor_ic_roll
                WHERE factor_name = ? AND window = 20
                ORDER BY as_of_date
            """, (fname,)).fetchall()
            vals = [float(r[1]) for r in hist if r[1] is not None]
            win_vals = [float(r[2]) for r in hist if r[2] is not None]
            if len(vals) >= 2:
                m = float(np.mean(vals))
                s = float(np.std(vals, ddof=1))
                ir = m / s if s > 0 else 0
                # 滚动胜率 = 历史每日信号胜率的均值（表内统一小数）
                w = float(np.mean(win_vals)) if win_vals else 0
                fusion_roll[fname] = {
                    'mean_ic': round(m, 4), 'std_ic': round(s, 4),
                    'icir': round(ir, 3), 'win_rate': round(w, 4),
                    'n_days': len(vals)
                }
        
        # 2. 模型 IC（从 ic_daily 表，取最近20个交易日均值 + 最新单日 + 滚动统计）
        model_ic = {}
        try:
            # 原始数据（最近20行，按信号日期降序）
            raw_rows = conn.execute("""
                SELECT ic_fusion, ic_reg20, ic_reg40, ic_reg10, ic_final
                FROM ic_daily
                ORDER BY signal_date DESC
                LIMIT 20
            """).fetchall()
            
            # 最新单日
            latest = conn.execute("""
                SELECT ic_fusion, ic_reg20, ic_reg40, ic_reg10, signal_date, sample_size
                FROM ic_daily ORDER BY signal_date DESC LIMIT 1
            """).fetchone()
            
            if raw_rows and latest:
                n = len(raw_rows)
                fusion_vals = [r[0] for r in raw_rows if r[0] is not None]
                reg20_vals = [r[1] for r in raw_rows if r[1] is not None]
                reg40_vals = [r[2] for r in raw_rows if r[2] is not None]
                reg10_vals = [r[3] for r in raw_rows if r[3] is not None]
                
                def roll_stats(vals):
                    if len(vals) < 2:
                        return 0, 0, 0, 0
                    mean = float(np.mean(vals))
                    std = float(np.std(vals, ddof=1))
                    ir = mean / std if std > 0 else 0
                    win = sum(1 for v in vals if v > 0) / len(vals)
                    return round(mean, 4), round(std, 4), round(ir, 4), round(win, 4)
                
                model_ic = {
                    'fusion': round(float(np.mean(fusion_vals)), 4) if fusion_vals else 0,
                    'reg20': round(float(np.mean(reg20_vals)), 4) if reg20_vals else 0,
                    'reg40': round(float(np.mean(reg40_vals)), 4) if reg40_vals else 0,
                    'reg10': round(float(np.mean(reg10_vals)), 4) if reg10_vals else 0,
                    'date': str(latest[4])[:10] if latest[4] else '-',
                    'samples': latest[5] or 0,
                    'window': n,
                }
                # 滚动统计：IR + 胜率
                f_mean, f_std, f_ir, f_win = roll_stats(fusion_vals)
                r10_mean, r10_std, r10_ir, r10_win = roll_stats(reg10_vals)
                r20_mean, r20_std, r20_ir, r20_win = roll_stats(reg20_vals)
                r40_mean, r40_std, r40_ir, r40_win = roll_stats(reg40_vals)
                model_ic.update({
                    'fusion_ir': f_ir, 'fusion_win': f_win,
                    'fusion_std': f_std,
                    'reg10_ir': r10_ir, 'reg10_win': r10_win,
                    'reg20_ir': r20_ir, 'reg20_win': r20_win,
                    'reg40_ir': r40_ir, 'reg40_win': r40_win,
                })
        except Exception:
            pass

        # 2.5 窗口期 IC（从 ic_window 表，2026-08-05 新增：真预测窗口验证）
        window_ic = {}
        try:
            wrows = conn.execute("""
                SELECT signal_date, n, ic_reg10_w10, ic_reg20_w20, ic_reg40_w40,
                       ic_fusion_w10, ic_fusion_w20, ic_fusion_w40,
                       ic_3f_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_center_w10, ic_dual_w10,
                       fwd10_top, fwd20_top, fwd40_top,
                       fwd10_top_3f, fwd10_top_cmmr, fwd10_top_cmmrf, fwd10_top_center, fwd10_top_dual,
                       fwd20_top_cmmrf, fwd40_top_cmmrf, fwd10_top_main, fwd20_top_main, fwd40_top_main,
                       fwd20_top_cmmr
                FROM ic_window ORDER BY signal_date DESC LIMIT 20
            """).fetchall()
            if wrows:
                wlatest = wrows[0]
                window_ic = {
                    'date': str(wlatest[0])[:10],
                    'n': wlatest[1] or 0,
                    'ic_reg10_w10': round(wlatest[2], 4) if wlatest[2] is not None else None,
                    'ic_reg20_w20': round(wlatest[3], 4) if wlatest[3] is not None else None,
                    'ic_reg40_w40': round(wlatest[4], 4) if wlatest[4] is not None else None,
                    'ic_fusion_w10': round(wlatest[5], 4) if wlatest[5] is not None else None,
                    'ic_fusion_w20': round(wlatest[6], 4) if wlatest[6] is not None else None,
                    'ic_fusion_w40': round(wlatest[7], 4) if wlatest[7] is not None else None,
                    'ic_3f_w10': round(wlatest[8], 4) if wlatest[8] is not None else None,
                    'ic_cmmr_w10': round(wlatest[9], 4) if wlatest[9] is not None else None,
                    'ic_cmmrf_w10': round(wlatest[10], 4) if wlatest[10] is not None else None,
                    'ic_center_w10': round(wlatest[11], 4) if wlatest[11] is not None else None,
                    'ic_dual_w10': round(wlatest[12], 4) if wlatest[12] is not None else None,
                    'fwd10_top': round(wlatest[13], 3) if wlatest[13] is not None else None,
                    'fwd20_top': round(wlatest[14], 3) if wlatest[14] is not None else None,
                    'fwd40_top': round(wlatest[15], 3) if wlatest[15] is not None else None,
                    'fwd10_top_3f': round(wlatest[16], 3) if wlatest[16] is not None else None,
                    'fwd10_top_cmmr': round(wlatest[17], 3) if wlatest[17] is not None else None,
                    'fwd10_top_cmmrf': round(wlatest[18], 3) if wlatest[18] is not None else None,
                    'fwd10_top_center': round(wlatest[19], 3) if wlatest[19] is not None else None,
                    'fwd10_top_dual': round(wlatest[20], 3) if wlatest[20] is not None else None,
                    'fwd20_top_cmmrf': round(wlatest[21], 3) if wlatest[21] is not None else None,
                    'fwd40_top_cmmrf': round(wlatest[22], 3) if wlatest[22] is not None else None,
                    'fwd10_top_main': round(wlatest[23], 3) if wlatest[23] is not None else None,
                    'fwd20_top_main': round(wlatest[24], 3) if wlatest[24] is not None else None,
                    'fwd40_top_main': round(wlatest[25], 3) if wlatest[25] is not None else None,
                    'fwd20_top_cmmr': round(wlatest[26], 3) if wlatest[26] is not None else None,
                    'series': [{
                        'date': str(r[0])[:10],
                        'ic_3f_w10': round(r[8], 4) if r[8] is not None else None,
                        'ic_cmmr_w10': round(r[9], 4) if r[9] is not None else None,
                        'ic_cmmrf_w10': round(r[10], 4) if r[10] is not None else None,
                        'ic_center_w10': round(r[11], 4) if r[11] is not None else None,
                        'ic_dual_w10': round(r[12], 4) if r[12] is not None else None,
                        'ic_fusion_w10': round(r[5], 4) if r[5] is not None else None,
                        'ic_fusion_w20': round(r[6], 4) if r[6] is not None else None,
                        'ic_fusion_w40': round(r[7], 4) if r[7] is not None else None,
                        'ic_reg10_w10': round(r[2], 4) if r[2] is not None else None,
                        'ic_reg20_w20': round(r[3], 4) if r[3] is not None else None,
                        'ic_reg40_w40': round(r[4], 4) if r[4] is not None else None,
                        'fwd10_top': round(r[13], 3) if r[13] is not None else None,
                        'fwd20_top': round(r[14], 3) if r[14] is not None else None,
                        'fwd40_top': round(r[15], 3) if r[15] is not None else None,
                        'fwd10_top_3f': round(r[16], 3) if r[16] is not None else None,
                        'fwd10_top_cmmr': round(r[17], 3) if r[17] is not None else None,
                        'fwd10_top_cmmrf': round(r[18], 3) if r[18] is not None else None,
                        'fwd10_top_center': round(r[19], 3) if r[19] is not None else None,
                        'fwd10_top_dual': round(r[20], 3) if r[20] is not None else None,
                        'fwd20_top_cmmrf': round(r[21], 3) if r[21] is not None else None,
                        'fwd40_top_cmmrf': round(r[22], 3) if r[22] is not None else None,
                        'fwd10_top_main': round(r[23], 3) if r[23] is not None else None,
                        'fwd20_top_main': round(r[24], 3) if r[24] is not None else None,
                        'fwd40_top_main': round(r[25], 3) if r[25] is not None else None,
                        'fwd20_top_cmmr': round(r[26], 3) if r[26] is not None else None,
                    } for r in wrows],
                }
        except Exception as e:
            print(f"窗口IC读取失败: {e}")
            window_ic = {}

        # 2.6 fusion_dual 组合 IC（2026-08-10 新增：动态计算，0.5*pct(fusion_3f)+0.5*pct(fusion_score)
        # 与策略账户 fusion_dual 同口径；8/3 起可信基线，逐信号日算次日 Spearman IC）
        dual_ic = {}
        try:
            import duckdb as _ddb
            tdu = _ddb.connect(str(TUSHARE_DB_PATH), read_only=True)
            tdays = [str(r[0]) for r in tdu.execute(
                "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
            td_idx = {d: i for i, d in enumerate(tdays)}
            sig_dates = [str(r[0]).replace('-', '') for r in conn.execute(
                "SELECT DISTINCT REPLACE(date,'-','') FROM fusion_3f_signals "
                "WHERE REPLACE(date,'-','') >= '20260803' ORDER BY 1").fetchall()]
            ic_list, sb_rets, top_rets, dates = [], [], [], []
            for sd in sig_dates:
                if sd not in td_idx or td_idx[sd] + 1 >= len(tdays):
                    continue  # 无次日收益（最新信号日），跳过
                nd = tdays[td_idx[sd] + 1]
                f3_rows = conn.execute(
                    "SELECT stock_code, fusion_3f_score FROM fusion_3f_signals "
                    "WHERE REPLACE(date,'-','')=? AND fusion_3f_score IS NOT NULL", (sd,)).fetchall()
                md_rows = conn.execute(
                    "SELECT stock_code, fusion_score FROM signal_history "
                    "WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL", (sd,)).fetchall()
                f3map = {r[0]: float(r[1]) for r in f3_rows}
                mdmap = {r[0]: float(r[1]) for r in md_rows}
                common = sorted(set(f3map) & set(mdmap))
                if len(common) < 1000:
                    continue
                n = len(common)
                f3_rank = np.argsort(np.argsort([f3map[x] for x in common])) + 1
                md_rank = np.argsort(np.argsort([mdmap[x] for x in common])) + 1
                comb = {x: 0.5 * f3_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
                        for i, x in enumerate(common)}
                closes = {}
                for d_ in (sd, nd):
                    for ts, c in tdu.execute("SELECT ts_code, close FROM daily WHERE trade_date=?",
                                             [d_]).fetchall():
                        closes.setdefault(ts, {})[d_] = float(c)
                rets, scores, sb_ret, top_ret = [], [], [], []
                ordered = sorted(comb.items(), key=lambda x: x[1], reverse=True)
                for i, (sc, s) in enumerate(ordered):
                    full = f"{sc}.SH" if sc.startswith(('6', '9')) else f"{sc}.SZ"
                    p = closes.get(full)
                    if not p or sd not in p or nd not in p:
                        continue
                    r = p[nd] / p[sd] - 1
                    rets.append(r); scores.append(s)
                    if i < int(n * 0.15):  # 强买=组合分前15%（与策略账户 fusion_dual 强买口径一致）；Top10=前10只执行口径
                        sb_ret.append(r)
                        if i < 10:
                            top_ret.append(r)
                if len(rets) < 1000:
                    continue
                ic = float(np.corrcoef(scores, rets)[0, 1])  # 与组合分单调性（Spearman 近似用 rank 分本身）
                ic_list.append(ic)
                sb_rets.append(float(np.mean(sb_ret)) if sb_ret else 0)
                top_rets.append(float(np.mean(top_ret)) if top_ret else 0)
                dates.append(str(sd))
            tdu.close()
            if ic_list:
                dual_ic = {
                    'date': dates[-1][:4] + '-' + dates[-1][4:6] + '-' + dates[-1][6:],
                    'mean_ic': round(float(np.mean(ic_list)), 4),
                    'win_rate': round(sum(1 for x in ic_list if x > 0) / len(ic_list), 4),
                    'sb_mean_ret': round(float(np.mean(sb_rets)), 4),
                    'sb_win': round(sum(1 for x in sb_rets if x > 0) / len(sb_rets), 4),
                    'top10_ret': round(float(np.mean(top_rets)), 4),
                    'top10_win': round(sum(1 for x in top_rets if x > 0) / len(top_rets), 4),
                    'n_days': len(ic_list),
                    'series': [{'date': dates[i][:4] + '-' + dates[i][4:6] + '-' + dates[i][6:],
                                'ic': round(ic_list[i], 4),
                                'sb_ret': round(sb_rets[i], 4),
                                'top10_ret': round(top_rets[i], 4)} for i in range(len(ic_list))],
                }
        except Exception as e:
            print(f"fusion_dual IC 计算失败: {e}")
            dual_ic = {}

        # 2.7 center_dual 组合 IC（2026-08-27：读 center_dual_ic_daily 表，由 center_dual_ic.py 每日落库）
        center_ic = {}
        try:
            crows = conn.execute(
                "SELECT date, ic, samples, top_ret, bottom_ret, fwd10_top10, fwd20_top10, fwd40_top10 "
                "FROM center_dual_ic_daily ORDER BY date").fetchall()
            if crows:
                ics = [r[1] for r in crows if r[1] is not None]
                # 最新非空的 10/20/40d 窗口收益（Top10 等权，center_dual_ic.py 已×100 落库为百分数）
                def _latest_fwd(idx):
                    for r in reversed(crows):
                        if r[idx] is not None:
                            return {'date': r[0][:4] + '-' + r[0][4:6] + '-' + r[0][6:],
                                    'ret': round(r[idx], 2)}
                    return None
                center_ic = {
                    'date': crows[-1][0][:4] + '-' + crows[-1][0][4:6] + '-' + crows[-1][0][6:],
                    'mean_ic': round(float(np.mean(ics)), 4),
                    'win_rate': round(sum(1 for x in ics if x > 0) / len(ics), 4),
                    'n_days': len(ics),
                    'fwd10': _latest_fwd(5),
                    'fwd20': _latest_fwd(6),
                    'fwd40': _latest_fwd(7),
                    'series': [{'date': r[0][:4] + '-' + r[0][4:6] + '-' + r[0][6:],
                                'ic': round(r[1], 4), 'top10_ret': round(r[3], 4),
                                'fwd10': round(r[5], 2) if r[5] is not None else None,
                                'fwd20': round(r[6], 2) if r[6] is not None else None,
                                'fwd40': round(r[7], 2) if r[7] is not None else None} for r in crows],
                }
        except Exception as e:
            print(f"center_dual IC 读取失败: {e}")
            center_ic = {}

        conn.close()
        
        # 3. ETF 模型 IC（从 etf_ic 表）
        etf_ic = {}
        try:
            conn2 = get_state_db()
            erow = conn2.execute("""
                SELECT ic_etf, ic_spearman, ic_20d, sample_size, ic_diff, signal_date
                FROM etf_ic ORDER BY calc_date DESC LIMIT 1
            """).fetchone()
            if erow:
                etf_ic = {
                    'ic_etf': round(erow[0] or 0, 4),
                    'ic_spearman': round(erow[1] or 0, 4) if erow[1] else 0,
                    'ic_20d': round(erow[2] or 0, 4) if erow[2] else 0,
                    'samples': erow[3] or 0,
                    'ic_diff': round(erow[4] or 0, 4),
                    'date': str(erow[5] or '')[:10],
                }
            conn2.close()
        except Exception:
            pass
        
        # 4. CMMR IC（新增：从 cmmr_ic_daily 和 fusion_ic_daily 表）
        # 2026-09-11 修口径：列表展示全部行（partial 也展示），但滚动统计只用
        # forward_days=20 的定稿行——旧数据 08-03~09-09 全是 1 日 IC（回填 bug 产物，
        # 已在 cmmr_ic_daily.py 修复并回填），与 20 日口径混在一起会把均值/IR 稀释成噪声。
        cmmr_ic = []
        fusion_ic = []
        cmmr_roll = {'cmmr': {}, 'fusion': {}}
        try:
            conn3 = get_state_db()
            cmmr_rows = conn3.execute("""
                SELECT date, ic, samples, COALESCE(forward_days,1) FROM cmmr_ic_daily ORDER BY date DESC LIMIT 60
            """).fetchall()
            fusion_rows = conn3.execute("""
                SELECT date, ic, samples, COALESCE(forward_days,1) FROM fusion_ic_daily ORDER BY date DESC LIMIT 60
            """).fetchall()
            
            cmmr_ic = [{'date': str(r[0])[:10], 'ic': round(r[1] or 0, 4), 'samples': r[2] or 0,
                        'forward_days': r[3]} for r in cmmr_rows[:20]]
            fusion_ic = [{'date': str(r[0])[:10], 'ic': round(r[1] or 0, 4), 'samples': r[2] or 0,
                          'forward_days': r[3]} for r in fusion_rows[:20]]

            # 滚动统计（与模型 IC 同口径：最近 N 条当日 IC 的均值/标准差/IR/胜率）
            def cmmr_roll_stats(vals):
                if len(vals) < 2:
                    return {'mean_ic': 0, 'std_ic': 0, 'icir': 0, 'win_rate': 0, 'n_days': len(vals)}
                mean = float(np.mean(vals))
                std = float(np.std(vals, ddof=1))
                ir = mean / std if std > 0 else 0
                win = sum(1 for v in vals if v > 0) / len(vals)
                return {'mean_ic': round(mean, 4), 'std_ic': round(std, 4),
                        'icir': round(ir, 3), 'win_rate': round(win, 4), 'n_days': len(vals)}

            # 滚动统计各取自己定稿窗（09-20 分窗：cmmr=10d / fusion=20d，口径隔离）
            cmmr_vals = [float(r[1]) for r in cmmr_rows if r[1] is not None and r[3] == 10]
            fusion_vals = [float(r[1]) for r in fusion_rows if r[1] is not None and r[3] == 20]
            cmmr_roll['cmmr'] = cmmr_roll_stats(cmmr_vals)
            cmmr_roll['fusion'] = cmmr_roll_stats(fusion_vals)

            # 组合口径轨（2026-09-20 新增）：80+ 池 top10 未来10日超额（账户真实选池键序）
            # 注意：get_state_db 的 main=ledger.db、signals.db attach 为 sig，
            # 存在性检查与查询都须走 sig. 前缀（裸 sqlite_master 只看 main，09-20 踩坑）
            top10_rows = conn3.execute("""
                SELECT date, top10_ret, pool_mean, mkt_median, excess_pool, excess_mkt,
                       n_pool, forward_days
                FROM sig.cmmr_top10_ic_daily ORDER BY date DESC LIMIT 60
            """).fetchall() if conn3.execute(
                "SELECT name FROM sig.sqlite_master WHERE type='table' AND name='cmmr_top10_ic_daily'"
            ).fetchone() else []
            top10_final = [r for r in top10_rows if r[7] == 10]
            cmmr_roll['top10'] = {
                'days': len(top10_final),
                'avg_excess_pool': round(float(np.mean([r[4] for r in top10_final])), 3) if top10_final else 0,
                'avg_excess_mkt': round(float(np.mean([r[5] for r in top10_final])), 3) if top10_final else 0,
                'win_vs_pool': round(sum(1 for r in top10_final if r[4] > 0) / len(top10_final), 3) if top10_final else 0,
                'win_vs_mkt': round(sum(1 for r in top10_final if r[5] > 0) / len(top10_final), 3) if top10_final else 0,
            }
            conn3.close()
        except Exception as e:
            print(f"CMMR IC 读取失败: {e}")
            pass
        
        self._json({"ic_data": ic_data, "model_ic": model_ic, "window_ic": window_ic, "etf_ic": etf_ic, "cmmr_ic": cmmr_ic, "fusion_ic": fusion_ic, "fusion_roll": fusion_roll, "cmmr_roll": cmmr_roll, "dual_ic": dual_ic, "center_ic": center_ic})
    
    def _handle_cron_jobs(self):
        """返回cron任务状态"""
        import json
        crondb = Path(os.path.expanduser('~/.hermes/cron/jobs.json'))
        if not crondb.exists():
            self._json({"jobs": [], "error": "cron.json 不存在"})
            return
        try:
            with open(crondb) as f:
                data = json.load(f)
            jobs = data.get('jobs', [])
            # 解析 schedule 为可读格式
            for j in jobs:
                sched = j.get('schedule', {})
                if isinstance(sched, dict):
                    expr = sched.get('display', sched.get('expr', ''))
                    # 简化显示
                    if '*-*' in expr or '*/' in expr:
                        pass  # keep as-is
                    elif expr.startswith('0 ') and ' * *' in expr:
                        parts = expr.split()
                        if len(parts) >= 3:
                            h, m = parts[1].zfill(2), parts[0].zfill(2)
                            day_map = {'1':'一','2':'二','3':'三','4':'四','5':'五','6':'六','0':'日'}
                            if parts[4] == '*':
                                j['schedule_display'] = f"\u6bcf\u5929 {h}:{m}"
                            elif parts[4] in day_map:
                                j['schedule_display'] = f"\u661f\u671f{day_map[parts[4]]} {h}:{m}"
                            else:
                                j['schedule_display'] = expr
                    else:
                        j['schedule_display'] = expr
                    # next run
                    if sched.get('kind') == 'once':
                        j['schedule_display'] = '\u4e00\u6b21\u6027: ' + sched.get('display', '')
                else:
                    j['schedule_display'] = str(sched)
                # 状态
                status = j.get('last_status', None)
                if status == 'ok':
                    j['status_icon'] = '\u2705'
                elif status == 'error':
                    j['status_icon'] = '\u274c'
                elif j.get('enabled') == False:
                    j['status_icon'] = '\u23f8\ufe0f'
                else:
                    j['status_icon'] = '\u23f3'
                # last run time
                last_at = j.get('last_run_at', '')
                if last_at:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(last_at)
                        j['last_run_display'] = dt.strftime('%m-%d %H:%M')
                    except:
                        j['last_run_display'] = str(last_at)[:16]
                else:
                    j['last_run_display'] = '-'
            # 排序：按每日执行时刻（分、时）升序，周内固定日（周六日）排尾；一次性任务按触发时间插入
            def _first_num(field):
                import re as _re
                if field == '*':
                    return 0
                nums = [int(x) for x in _re.findall(r'\d+', field)]
                return min(nums) if nums else 0
            def _sort_key(j):
                sched = j.get('schedule', {})
                if isinstance(sched, dict) and sched.get('kind') == 'once':
                    return (9, 0, str(sched.get('display', '')))
                expr = sched.get('expr', '') if isinstance(sched, dict) else str(sched)
                parts = expr.split()
                if len(parts) >= 5:
                    minute, hour, dow = _first_num(parts[0]), _first_num(parts[1]), _first_num(parts[4])
                    day_rank = 1 if parts[4] in ('1-5',) else (2 if parts[4] not in ('*', '1-5') else 0)
                    return (day_rank, hour * 60 + minute, j.get('name', ''))
                return (3, 0, j.get('name', ''))
            jobs.sort(key=_sort_key)
            self._json({"jobs": jobs})
        except Exception as e:
            self._json({"error": str(e)})

    def _handle_etf_list(self):
        """ETF分类列表（热门/宽基/科技）"""
        from core.db import get_tushare_db
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        cat = params.get("cat", [""])[0]
        tconn = get_tushare_db()
        try:
            if cat == "热门":
                rows = tconn.execute("SELECT ts_code, name, fund_type FROM fund_basic WHERE fund_type='股票型' ORDER BY list_date DESC LIMIT 20").fetchall()
            elif cat == "宽基":
                rows = tconn.execute("SELECT ts_code, name, fund_type FROM fund_basic WHERE name LIKE '%指数%' ORDER BY list_date DESC LIMIT 30").fetchall()
            elif cat == "科技":
                rows = tconn.execute("SELECT ts_code, name, fund_type FROM fund_basic WHERE name LIKE '%科技%' OR name LIKE '%科创%' OR name LIKE '%半导体%' OR name LIKE '%芯片%' OR name LIKE '%AI%' OR name LIKE '%新能源%' ORDER BY list_date DESC LIMIT 30").fetchall()
            else:
                rows = tconn.execute("SELECT ts_code, name, fund_type FROM fund_basic ORDER BY list_date DESC LIMIT 30").fetchall()
            tconn.close()
            lst = [{"ts_code": r[0], "name": r[1], "fund_type": r[2], "score": None} for r in rows]
            self._json({"list": lst})
        except Exception as e:
            tconn.close()
            self._json({"error": str(e)})

    def _handle_etf_rank(self):
        """全市场ETF评分排名"""
        from core.db import get_tushare_db
        from core.scoring import score_etf
        tconn = get_tushare_db()
        rows = tconn.execute("SELECT f.ts_code, f.name FROM fund_basic f INNER JOIN (SELECT ts_code, COUNT(*) as cnt FROM fund_daily GROUP BY ts_code HAVING cnt >= 150) d ON f.ts_code = d.ts_code ORDER BY d.cnt DESC").fetchall()
        tconn.close()
        results = []
        for i, (code, name) in enumerate(rows):
            try:
                sr = score_etf(code)
                if sr and sr['score'] is not None:
                    results.append((code, name, sr['score'], sr['prediction']))
            except:
                pass
        results.sort(key=lambda x: x[2], reverse=True)
        top = [{"ts_code": r[0], "name": r[1], "score": r[2], "prediction": r[3]} for r in results[:20]]
        self._json({"list": top, "total": len(results)})

    def _handle_etf_scores(self):
        """返回 ETF 评分排名列表"""
        sdb = get_state_db()
        try:
            rows = sdb.execute("""
                SELECT ts_code, name, score, prediction, scan_date
                FROM etf_scores ORDER BY score DESC
            """).fetchall()
            lst = [{
                "ts_code": r[0], "name": r[1],
                "score": r[2], "prediction": r[3],
                "scan_date": r[4]
            } for r in rows]
            self._json({"list": lst, "total": len(lst)})
        except Exception as e:
            self._json({"list": [], "error": str(e)})
        finally:
            sdb.close()

    def _handle_etf_analyze(self, code):
        """ETF诊断：技术面 + 模型评分（优先用缓存评分）"""
        from core.db import get_tushare_db
        from core.scoring import score_etf
        if "." not in code:
            code = f"{code}.SH"
        
        # 先查缓存
        cached_result = None
        try:
            sdb = get_state_db()
            row = sdb.execute("SELECT score, prediction FROM etf_scores WHERE ts_code=?", (code,)).fetchone()
            if row:
                cached_result = {"score": row[0], "prediction": row[1]}
            sdb.close()
        except:
            pass
        
        tconn = get_tushare_db()
        name = code
        try:
            r = tconn.execute("SELECT name FROM fund_basic WHERE ts_code=?", (code,)).fetchone()
            if r: name = r[0]
        except:
            pass
        
        # 有缓存就不用实时算了
        result = cached_result or score_etf(code)
        price = None
        change = None
        try:
            row = tconn.execute("SELECT close, pct_chg FROM fund_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", (code,)).fetchone()
            if row:
                price = float(row[0])
                change = float(row[1])
        except:
            pass
        tconn.close()
        report_lines = []
        report_lines.append(f"📊 {name} ({code}) ETF诊断")
        if price is not None:
            report_lines.append(f"现价: {price:.4f} | 涨跌: {change:+.2f}%")
        if result:
            report_lines.append(f"🎯 模型评分: {result['score']}分")
            report_lines.append(f"   20d预测: {result['prediction']}%")
            if result["score"] >= 70:
                report_lines.append("✅ 偏多，可关注")
            elif result["score"] >= 40:
                report_lines.append("◻ 中性")
            else:
                report_lines.append("⚠️ 偏弱")
        else:
            report_lines.append("❌ 无评分数据")
        self._json({
            "ts_code": code,
            "name": name,
            "price": price,
            "change_pct": change,
            "model_prediction": result["prediction"] if result else None,
            "model_score": result["score"] if result else None,
            "report": "\n".join(report_lines),
        })
    def _handle_analyze(self, code):
        """个股诊断：技术面+评分+资金流"""
        if '.' not in code:
            code = f"{code}.SH" if code.startswith('6') else f"{code}.SZ"
        cs = code.replace('.SH','').replace('.SZ','')
        from core.db import get_tushare_db
        import time
        conn = None
        for attempt in range(5):
            try:
                conn = get_tushare_db()
                break
            except Exception:
                if attempt < 4: time.sleep(2)
                else:
                    self._json({"error": "数据库被占用"})
                    return
        basic = conn.execute("SELECT name, industry FROM stock_basic WHERE ts_code=?", [code]).fetchone()
        if not basic:
            conn.close()
            self._json({"error": f"未找到 {code}"})
            return
        name, industry = basic
        rows = conn.execute(f"""SELECT trade_date, close, pct_chg, vol, amount FROM daily WHERE ts_code='{code}' ORDER BY trade_date DESC LIMIT 120""").fetchall()
        if len(rows) < 10:
            conn.close()
            self._json({"error": f"日线不足({len(rows)})"})
            return
        closes = [float(r[1]) for r in rows]
        pcts = [float(r[2]) for r in rows]
        vols = [float(r[3]) for r in rows]
        dates = [str(r[0]) for r in rows]
        lp = closes[0]
        prev = closes[1] if len(closes)>1 else lp
        chg = round((lp/prev-1)*100,2)
        ma5 = sum(closes[:5])/5 if len(closes)>=5 else None
        ma10 = sum(closes[:10])/10 if len(closes)>=10 else None
        ma20 = sum(closes[:20])/20 if len(closes)>=20 else None
        ma60 = sum(closes[:60])/60 if len(closes)>=60 else None
        ma120 = sum(closes[:120])/120 if len(closes)>=120 else None
        avgv5 = sum(vols[1:6])/5 if len(vols)>=6 else None
        vr = round(vols[0]/avgv5,2) if avgv5 and avgv5>0 else None
        dev120 = round((lp-ma120)/ma120*100,2) if ma120 else None
        chg60 = round((closes[0]/closes[min(59,len(closes)-1)]-1)*100,2) if len(closes)>=60 else None
        mf_rows = conn.execute(f"SELECT date, main_net FROM money_flow WHERE stock_code='{cs}' ORDER BY date DESC LIMIT 5").fetchall()
        mf = []
        mf_total = 0
        for r in mf_rows:
            v = float(r[1])/10000 if r[1] else 0
            mf.append({"date": str(r[0])[:10], "net": round(v,2)})
            mf_total += v
        mf_today = round(mf[0]["net"],2) if mf else None
        if mf_today is not None and abs(mf_today) < 0.01:
            raw = float(mf_rows[0][1]) if mf_rows and mf_rows[0][1] else 0
            mf_disp = f"{raw:+.0f}万"
        elif mf_today is not None:
            mf_disp = f"{mf_today:+.2f}亿"
        else:
            mf_disp = None
        if mf and abs(mf_total) < 0.01:
            mf5d = f"{sum(float(m[1] or 0) for m in mf_rows):+.0f}万"
        elif mf:
            mf5d = f"{mf_total:+.2f}亿"
        else:
            mf5d = None
        fusion = reg10 = reg20 = reg40 = None
        try:
            from core.scoring import score_stock
            sr = score_stock(cs)
            if sr:
                fusion = round(sr.get('fusion',0),1)
                reg10 = round(sr.get('reg10_pred',0),2)
                reg20 = round(sr.get('reg20_pred',0),1)
                reg40 = round(sr.get('reg40_pred',0),1)
        except:
            pass

        # 评分历史 (从 signals.db signal_history)
        score_history = []
        try:
            import sqlite3
            sdb = sqlite3.connect(str(Path.home() / '.hermes' / 'stockdb' / 'signals.db'))  # v2温层: signal_history
            sdb.row_factory = sqlite3.Row
            sh_rows = sdb.execute(f"""
                SELECT date, fusion_score, reg20, reg40, reg10 
                FROM signal_history 
                WHERE stock_code = '{cs}' OR stock_code = '{code}'
                ORDER BY REPLACE(date, '-', '') ASC
            """).fetchall()
            for r in sh_rows:
                d = str(r['date'])
                d_clean = d.replace('-', '')[:8]
                # 查当日收盘价
                close_price = None
                try:
                    cp = conn.execute(f"SELECT close FROM daily WHERE ts_code = '{code}' AND trade_date = '{d_clean}'").fetchone()
                    if cp: close_price = float(cp[0])
                except:
                    pass
                fusion_val = round(r['fusion_score'] or 0, 1)
                reg20_val = round(r['reg20'] or 0, 2)
                reg40_val = round(r['reg40'] or 0, 2)
                reg10_val = round(r['reg10'] or 0, 4)
                # 跳过：休市日(无股价说明无交易)
                if close_price is None:
                    continue
                score_history.append({
                    'date': d_clean,
                    'close': close_price,
                    'fusion': fusion_val,
                    'reg20': reg20_val,
                    'reg40': reg40_val,
                    'reg10': reg10_val,
                })
            sdb.close()
        except Exception:
            pass
        conn.close()

        # Build report
        rp = []
        rp.append(f"📊 {name} ({cs}) 诊断报告")
        rp.append(f"行业：{industry} | 日期：{dates[0]}")
        rp.append(f"现价：{lp:.2f} | 涨跌：{chg:+.2f}% | 量比：{vr if vr else '-'}")
        if chg60: rp.append(f"60日涨跌：{chg60:+.1f}%")
        ma_p = []
        if ma5: ma_p.append(f"MA5={ma5:.2f}{chr(8593) if lp>ma5 else chr(8595)}")
        if ma10: ma_p.append(f"MA10={ma10:.2f}{chr(8593) if lp>ma10 else chr(8595)}")
        if ma20: ma_p.append(f"MA20={ma20:.2f}{chr(8593) if lp>ma20 else chr(8595)}")
        if ma60: ma_p.append(f"MA60={ma60:.2f}{chr(8593) if lp>ma60 else chr(8595)}")
        if ma120: ma_p.append(f"MA120={ma120:.2f}{chr(8593) if lp>ma120 else chr(8595)}")
        rp.append(f"均线：{' | '.join(ma_p)}")
        if ma5 and ma20 and ma60:
            if ma5>ma20>ma60: rp.append("✅多头排列(5>20>60)")
            elif ma5<ma20<ma60: rp.append("⚠️空头排列(5<20<60)")
            elif ma5>ma20: rp.append("◻短期偏多(5>20)")
            else: rp.append("◻短期偏空(5<20)")
        if dev120 is not None:
            if abs(dev120)<3: rp.append(f"贴近年线({dev120:+.1f}%)")
            elif dev120>0: rp.append(f"年线上方{dev120:.1f}%")
            else: rp.append(f"年线下方{abs(dev120):.1f}%")
        if vr: rp.append(f"量能{'放量' if vr>1.3 else '缩量' if vr<0.7 else '正常'}(x{vr:.1f})")
        if len(closes)>=20:
            lo=min(closes[:20]); hi=max(closes[:20])
            pp=(lp-lo)/(hi-lo)*100
            rp.append(f"20日区间：{lo:.2f}~{hi:.2f}，当前位于{pp:.0f}%分位")
        if len(pcts)>=5:
            up5=sum(1 for p in pcts[:5] if p>0)
            dn5=sum(1 for p in pcts[:5] if p<0)
            if up5>=4: rp.append("📈近5日强势(4阳+)")
            elif dn5>=4: rp.append("📉近5日弱势(4阴+)")
            elif up5>=3: rp.append("◻近5日偏多")
            elif dn5>=3: rp.append("◻近5日偏空")
        if mf_disp: rp.append(f"主力资金：{mf_disp}(5日累计：{mf5d})")
        rp.append("---")
        if fusion is not None:
            rp.append(f"🎯融合评分：{fusion:.0f}分")
            rp.append(f"   10d={reg10:+.1f}% | 20d={reg20:+.1f}% | 40d={reg40:+.1f}%")
            if fusion>=70: rp.append("✅强势股(前30%)")
            elif fusion>=50: rp.append("◻中性股")
            else: rp.append("⚠️弱势股(后50%)")
        vt = []
        tr = sum(1 for t in [lp>(ma5 or 0),lp>(ma20 or 0),lp>(ma60 or 0),lp>(ma120 or 0)] if t)
        if tr>=3: vt.append("多周期共振偏多")
        elif tr<=1: vt.append("多周期共振偏空")
        if len(closes)>=20:
            if pp>=90: vt.append(f"接近20日箱顶({pp:.0f}%)")
            elif pp<=10: vt.append(f"接近20日箱底({pp:.0f}%)")
        if mf:
            mt=sum(d["net"] for d in mf)
            if mt>0: vt.append(f"5日主力净流入{mf5d}")
            elif mt<0: vt.append(f"5日主力净流出{mf5d}")
        pv = sum(1 for t in vt if "偏多" in t or "突破" in t or "净流入" in t or "箱底" in t)
        nv = sum(1 for t in vt if "偏空" in t or "下跌" in t or "净流出" in t or "箱顶" in t)
        if pv>=2 and pv>nv: vd="偏多"
        elif nv>=2 and nv>pv: vd="偏空"
        else: vd="震荡"
        for l in vt: rp.append(l)
        rp.append(f"判断：{vd}(多{pv}/空{nv})")
        rp.append(f"判断：{vd}(多{pv}/空{nv})")
        report = "\n".join(rp)
        self._json({
            "code":cs,"name":name,"industry":industry,"date":dates[0],
            "price":lp,"change_pct":chg,"vol_ratio":vr,"chg60":chg60,
            "ma":{"ma5":ma5,"ma10":ma10,"ma20":ma20,"ma60":ma60,"ma120":ma120},
            "dev120":dev120,
            "money_flow":mf_today,"money_flow_display":mf_disp,"money_flow_5d":mf5d,"money_flow_detail":mf,
            "fusion_score":fusion,"reg10":reg10,"reg20":reg20,"reg40":reg40,
            "bullish_count":0,"verdict":vd,
            "score_history":score_history,
            "report":report,
        })

    def _handle_fusion3f_watchlist(self):
        """返回三因子融合观察名单"""
        conn = get_state_db()
        rows = conn.execute("""
            SELECT f.stock_code, f.fusion_3f_score, f.signal, f.date,
                   f.reg10, f.ma_decay, f.flow_alpha, f.vol_adj
            FROM fusion_3f_signals f
            WHERE REPLACE(f.date, '-', '') = (
                SELECT MAX(REPLACE(date, '-', '')) FROM fusion_3f_signals
            )
            ORDER BY f.fusion_3f_score DESC
            LIMIT 50
        """).fetchall()
        conn.close()
        
        info = self._stock_info_map({str(r[0]) for r in rows})
        items = []
        for r in rows:
            nm, ind = info.get(str(r[0]), ('', ''))
            items.append({
                'stock_code': r[0],
                'fusion_score': round(r[1] or 0, 1),
                'signal': r[2] or '',
                'date': str(r[3] or '')[:10],
                'reg10': round(r[4] or 0, 4),
                'ma_decay': round(r[5] or 0, 4),
                'flow_alpha': round(r[6] or 0, 4),
                'vol_adj': round(r[7] or 0, 4),
                'stock_name': nm or r[0],
                'industry': ind,
            })
        self._json({"items": items, "count": len(items)})

    def _handle_cmmr_watchlist(self):
        """返回 CMMR 独立策略观察名单"""
        conn = get_state_db()
        rows = conn.execute("""
            SELECT s.stock_code, s.cmmr_score, s.ma40_slope, s.date
            FROM signal_history s
            WHERE REPLACE(s.date, '-', '') = (
                SELECT MAX(REPLACE(date, '-', '')) FROM signal_history
                WHERE cmmr_score IS NOT NULL
            )
            AND s.cmmr_score IS NOT NULL
            ORDER BY s.cmmr_score DESC
            LIMIT 50
        """).fetchall()
        conn.close()
        info = self._stock_info_map({str(r[0]) for r in rows})
        items = []
        for r in rows:
            nm, ind = info.get(str(r[0]), ('', ''))
            items.append({
                'stock_code': r[0],
                'cmmr_score': round(r[1] or 0, 1),
                'ma40_slope': round(r[2] or 0, 4),
                'date': str(r[3] or '')[:10],
                'stock_name': nm or r[0],
                'industry': ind,
            })
        self._json({"items": items, "count": len(items)})

    def _handle_cmmr_fusion_watchlist(self):
        """返回 CMMR+ 模型融合观察名单（原名"三因子融合"系误称：old_score=三模型融合分，2026-08-10 更正）"""
        conn = get_state_db()
        rows = conn.execute("""
            SELECT s.stock_code, s.fusion_score_cmmr, s.cmmr_score, s.ma40_slope, s.date
            FROM signal_history s
            WHERE REPLACE(s.date, '-', '') = (
                SELECT MAX(REPLACE(date, '-', '')) FROM signal_history
                WHERE fusion_score_cmmr IS NOT NULL
            )
            AND s.fusion_score_cmmr IS NOT NULL
            ORDER BY s.fusion_score_cmmr DESC
            LIMIT 50
        """).fetchall()
        conn.close()
        info = self._stock_info_map({str(r[0]) for r in rows})
        items = []
        for r in rows:
            nm, ind = info.get(str(r[0]), ('', ''))
            items.append({
                'stock_code': r[0],
                'fusion_score': round(r[1] or 0, 1),
                'cmmr_score': round(r[2] or 0, 1),
                'ma40_slope': round(r[3] or 0, 4),
                'date': str(r[4] or '')[:10],
                'stock_name': nm or r[0],
                'industry': ind,
            })
        self._json({"items": items, "count": len(items)})

    def _handle_fusion_center_watchlist(self):
        """返回中枢版融合观察名单（2026-08-06 新增：强买前15%，score=-(|ma_z|+|flow_z|+|vol_z|)）"""
        conn = get_state_db()
        rows = conn.execute("""
            SELECT f.stock_code, f.score, f.rank_pct, f.signal, f.date,
                   f.stock_name, f.industry
            FROM fusion_center_signals f
            WHERE REPLACE(f.date, '-', '') = (
                SELECT MAX(REPLACE(date, '-', '')) FROM fusion_center_signals
            )
            ORDER BY f.score DESC
            LIMIT 50
        """).fetchall()
        conn.close()
        items = []
        for r in rows:
            items.append({
                'stock_code': r[0],
                'score': round(r[1] or 0, 4),
                'rank_pct': round((r[2] or 0) * 100, 1),
                'signal': r[3] or '',
                'date': str(r[4] or '')[:10],
                'stock_name': r[5] or '',
                'industry': r[6] or '',
            })
        self._json({"items": items, "count": len(items)})

    def _handle_fusion_dual_watchlist(self):
        """三因子+三模型 组合观察名单（2026-08-10 新增：与策略账户 fusion_dual 同口径，
        组合分 = 0.5*pct(fusion_3f_score) + 0.5*pct(fusion_score)，前 15% 标强买）"""
        conn = get_state_db()
        d = conn.execute("SELECT MAX(REPLACE(date,'-','')) FROM fusion_3f_signals").fetchone()[0]
        f3_rows = conn.execute("""
            SELECT stock_code, fusion_3f_score FROM fusion_3f_signals
            WHERE REPLACE(date,'-','')=? AND fusion_3f_score IS NOT NULL
        """, (d,)).fetchall()
        md_rows = conn.execute("""
            SELECT stock_code, fusion_score, stock_name, industry FROM signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL
        """, (d,)).fetchall()
        conn.close()
        f3map = {r[0]: float(r[1]) for r in f3_rows}
        mdmap = {r[0]: (float(r[1]), r[2] or '', r[3] or '') for r in md_rows}
        common = sorted(set(f3map) & set(mdmap))
        items = []
        if common:
            n = len(common)
            f3_rank = np.argsort(np.argsort([f3map[c] for c in common])) + 1
            md_rank = np.argsort(np.argsort([mdmap[c][0] for c in common])) + 1
            comb = {c: 0.5 * f3_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
                    for i, c in enumerate(common)}
            th = float(np.percentile(list(comb.values()), 85))
            top = sorted(comb.items(), key=lambda x: x[1], reverse=True)[:50]
            for c, s in top:
                nm, ind = mdmap[c][1], mdmap[c][2]
                items.append({
                    'stock_code': c, 'stock_name': nm, 'industry': ind,
                    'f3_score': round(f3map[c], 2), 'md_score': round(mdmap[c][0], 2),
                    'comb_score': round(s, 2),
                    'signal': '强买' if s >= th else '',
                    'date': str(d)[:10],
                })
        self._json({"items": items, "count": len(items), "signal_date": str(d)[:10]})

    def _handle_center_dual_watchlist(self):
        """中枢版+三模型 组合观察名单（2026-08-27 新增：与策略账户 center_dual 同口径，
        组合分 = 0.5*pct(fusion_center score) + 0.5*pct(fusion_score)，前 15% 标强买）"""
        conn = get_state_db()
        d = conn.execute("SELECT MAX(REPLACE(date,'-','')) FROM fusion_center_signals").fetchone()[0]
        ct_rows = conn.execute("""
            SELECT stock_code, score FROM fusion_center_signals
            WHERE REPLACE(date,'-','')=? AND score IS NOT NULL
        """, (d,)).fetchall()
        md_rows = conn.execute("""
            SELECT stock_code, fusion_score, stock_name, industry FROM signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL
        """, (d,)).fetchall()
        conn.close()
        ctmap = {r[0]: float(r[1]) for r in ct_rows}
        mdmap = {r[0]: (float(r[1]), r[2] or '', r[3] or '') for r in md_rows}
        common = sorted(set(ctmap) & set(mdmap))
        items = []
        if common:
            n = len(common)
            ct_rank = np.argsort(np.argsort([ctmap[c] for c in common])) + 1
            md_rank = np.argsort(np.argsort([mdmap[c][0] for c in common])) + 1
            comb = {c: 0.5 * ct_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
                    for i, c in enumerate(common)}
            th = float(np.percentile(list(comb.values()), 85))
            top = sorted(comb.items(), key=lambda x: x[1], reverse=True)[:50]
            for c, s in top:
                nm, ind = mdmap[c][1], mdmap[c][2]
                items.append({
                    'stock_code': c, 'stock_name': nm, 'industry': ind,
                    'ct_score': round(ctmap[c], 3), 'md_score': round(mdmap[c][0], 2),
                    'comb_score': round(s, 2),
                    'signal': '强买' if s >= th else '',
                    'date': str(d)[:10],
                })
        self._json({"items": items, "count": len(items), "signal_date": str(d)[:10]})

    def _handle_shadow(self):
        """影子链监控页（2026-09-06 上线）：shadow_B / v4_big / v4d 三条影子链
        数据：signals.db shadow_*_scores + ic_shadow（NW判定由本端现算，lag10，与 shadow_ic_check.py 同式）"""
        import sqlite3, math, pandas as pd
        sdb = sqlite3.connect(str(BASE / 'signals.db'))
        out = {}
        try:
            # 1) 各影子链打分覆盖（影子B 09-21 退役，表已删）
            cov = {}
            for tbl, key in [('shadow_v4big_scores', 'v4big'),
                             ('shadow_v4d_scores', 'v4d'), ('shadow_v4e_scores', 'v4e')]:
                r = sdb.execute(f"SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM {tbl}").fetchone()
                cov[key] = {'first': str(r[0]), 'last': str(r[1]), 'days': int(r[2] or 0)}
            out['coverage'] = cov
            # 2) IC 对拍历史
            hist = pd.read_sql_query(
                "SELECT signal_date,n,ic_shadow_b,ic_reg10,ic_fusion,ic_v4big,ic_v4d,ic_v4e "
                "FROM ic_shadow ORDER BY signal_date", sdb)
            # NaN→null：where(...,None) 在 float 列会回退成 NaN，浏览器 JSON.parse 直接炸（0906 踩坑）
            out['ic_history'] = json.loads(hist.to_json(orient='records'))
            # 3) NW(lag10) 配对判定（与 shadow_ic_check.py 同式）
            def nw(d):
                d = np.asarray(d, dtype=float)
                d = d[np.isfinite(d)]  # NaN差值→NaN会让响应体带裸NaN(非法JSON)，浏览器JSON.parse整页崩（0915修）
                n = len(d)
                if n < 2: return None
                e = d - d.mean()
                var = float(e @ e / n)
                for lag in range(1, 11):
                    w = 1 - lag / 11.0
                    var += 2 * w * float(e[lag:] @ e[:-lag] / n)
                se = math.sqrt(max(var, 1e-18) / n)
                t = float(d.mean() / se)
                p = float(2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2)))))
                return {'mean': round(float(d.mean()), 5), 'nw_t': round(t, 2), 'nw_p': round(p, 4), 'n': int(n),
                        'verdict': ('✅ 达标可议换产' if (n >= 30 and p < 0.05 and d.mean() > 0)
                                    else ('❌ 已足样本未达标' if n >= 30 else f'观察中·还需约{max(30-n,0)}个成熟日'))}
            hv = hist.dropna(subset=['ic_v4big'])
            hd = hist.dropna(subset=['ic_v4d'])
            tests = {}
            # B-reg10 腿 09-21 退役（B 分已归档 retire/，不再现算判定）
            if len(hv) >= 2:
                tests['v4big-reg10'] = nw((hv['ic_v4big'] - hv['ic_reg10']).to_numpy())
            if len(hd) >= 2:
                d4 = hd['ic_v4d'].to_numpy() - hv['ic_v4big'].reindex(hd.index).to_numpy()
                ok = np.isfinite(d4); tests['v4d-v4big'] = nw(d4[ok])
            he = hist.dropna(subset=['ic_v4e'])
            if len(he) >= 2:
                d5 = he['ic_v4e'].to_numpy() - hd['ic_v4d'].reindex(he.index).to_numpy()
                ok5 = np.isfinite(d5); tests['v4e-v4d'] = nw(d5[ok5])
            out['tests'] = {k: v for k, v in tests.items() if v}
            # 4) 最新一天三方 top20 对比（同一批股票，标注 v4d 独有进榜票）
            last_d = cov['v4d']['last']
            rows_d = None
            if last_d:
                a = pd.read_sql_query("SELECT code,score FROM shadow_v4d_scores WHERE date=?", sdb, params=(last_d,))
                b = pd.read_sql_query("SELECT code,score FROM shadow_v4big_scores WHERE date=?", sdb, params=(last_d,))
                m = a.merge(b, on='code', how='left', suffixes=('_4d', '_4b'))
                m = m.rename(columns={'score': 'score_d'})
                top_d = set(m.nlargest(20, 'score_4d')['code']); top_b = set(m.nlargest(20, 'score_4b')['code'])
                m = m.nlargest(20, 'score_4d')
                info = self._stock_info_map({str(x) for x in m['code']})
                corr = float(m['score_4d'].corr(m['score_4b'])) if len(m) > 2 else None
                rows_d = [{'code': r['code'], 'name': info.get(str(r['code']), ('', ''))[0] or r['code'],
                           'industry': info.get(str(r['code']), ('', ''))[1],
                           'score_4d': round(float(r['score_4d']), 4) if pd.notna(r['score_4d']) else None,
                           'score_4b': round(float(r['score_4b']), 4) if pd.notna(r['score_4b']) else None,
                           # score_b 列随影子B退役移除（原为 score_d 冗余回显）
                           'rank_4b': None, 'only_v4d': r['code'] in (top_d - top_b)} for _, r in m.iterrows()]
                rb = m.copy(); rb['rk'] = m['score_4b'].rank(ascending=False)
                rk_map = dict(zip(rb['code'], rb['rk']))
                for row in rows_d:
                    v = rk_map.get(row['code'])
                    row['rank_4b'] = int(v) if v is not None and pd.notna(v) else None
                out['top20'] = {'date': last_d, 'rows': rows_d, 'corr_v4d_v4big': round(corr, 4) if corr is not None else None,
                                'top20_overlap': len(top_d & top_b)}
        finally:
            sdb.close()
        self._json(out)

    def _handle_opinions(self):
        """盘中意见留档（2026-08-30 上线）：读 analysis/opinion_log.jsonl + 当日关注池概要"""
        analysis = BASE / 'analysis'
        log_p = analysis / 'opinion_log.jsonl'
        entries = []
        if log_p.exists():
            lines = log_p.read_text(encoding='utf-8').strip().splitlines()[-300:]
            for ln in lines:
                try:
                    entries.append(json.loads(ln))
                except Exception:
                    pass
        entries.reverse()  # 新→旧
        uni_summary = {}
        uni_p = analysis / 'opinion_universe.json'
        if uni_p.exists():
            try:
                u = json.loads(uni_p.read_text(encoding='utf-8'))
                uni_summary = {
                    'signal_date': u.get('signal_date'),
                    'generated_at': u.get('generated_at'),
                    'n_universe': len(u.get('universe', {})),
                    'top10': u.get('top10', {}),
                    'accounts': u.get('accounts', {}),
                }
            except Exception:
                pass
        self._json({"entries": entries, "count": len(entries), "universe": uni_summary})

    def log_message(self, fmt, *args):
        pass


def main():
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", PORT), DashboardHandler)
    print(f"Dashboard: http://localhost:{PORT}/dashboard.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

if __name__ == "__main__":
    main()
