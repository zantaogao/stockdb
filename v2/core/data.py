"""
v2 数据加载 — 从 stock.db 提取训练/推理所需全部数据
"""
import duckdb
import numpy as np
from pathlib import Path

DB_PATH = Path.home() / '.hermes' / 'stockdb' / 'stock.db'


def connect():
    return duckdb.connect(str(DB_PATH), read_only=True)


def get_stock_list(conn=None):
    """获取有效股票列表（排除ST、北交所、无财务/估值数据的）"""
    c = conn or connect()
    try:
        rows = c.execute("""
            SELECT si.stock_code, si.stock_name, si.industry, si.board
            FROM stock_info si
            WHERE si.stock_code NOT LIKE '8%'
              AND si.stock_code NOT LIKE '4%'
              AND si.stock_code NOT LIKE '92%'
              AND (si.stock_name IS NULL OR si.stock_name NOT LIKE '%ST%')
              AND si.board != '北交所'
        """).fetchall()

        # 过滤有估值数据的
        val_codes = {r[0] for r in c.execute(
            "SELECT DISTINCT stock_code FROM stock_valuation"
        ).fetchall()}

        result = []
        for code, name, industry, board in rows:
            if code not in val_codes:
                continue
            # 映射行业到基准指数
            index_code = _get_bench_index(code)
            result.append({
                'code': code,
                'name': name or '',
                'industry': industry or '',
                'board': board or '',
                'bench': index_code,
            })

        return result
    finally:
        if c is not None and conn is None:
            c.close()


def _get_bench_index(code):
    """根据股票代码返回对应基准指数"""
    if code.startswith('688'):
        return '000688'   # 科创50
    elif code.startswith(('30', '301')):
        return '399006'   # 创业板指
    elif code.startswith('002') or code.startswith('00'):
        return '000905'   # 中证500（中小盘）
    else:
        return '000300'   # 沪深300（大盘）


def load_stock_data(code, bench_code='000300', max_days=300):
    """
    加载单只股票的全部数据，用于特征计算。

    Returns:
        dict with keys: daily_rows, limit_rows, mf_rows, val_dict, fin_dict, bench_closes, dates
        or None if insufficient data
    """
    conn = connect()
    try:
        # 日K线 (DESC)
        daily_rows = conn.execute(f"""
            SELECT date, open, close, high, low, volume, amount, amplitude, change_pct, turn_rate
            FROM stock_daily
            WHERE stock_code = '{code}'
            ORDER BY date DESC LIMIT {max_days}
        """).fetchall()

        if not daily_rows or len(daily_rows) < 120:
            return None

        # 涨跌停价 (DESC, 匹配日K时间范围)
        limit_rows = conn.execute(f"""
            SELECT date, up_limit, down_limit
            FROM stk_limit
            WHERE stock_code = '{code}'
            ORDER BY date DESC LIMIT {max_days}
        """).fetchall()

        # 资金流 (DESC)
        mf_rows = conn.execute(f"""
            SELECT trade_date, buy_sm_amount, sell_sm_amount,
                   buy_md_amount, sell_md_amount,
                   buy_lg_amount, sell_lg_amount,
                   buy_elg_amount, sell_elg_amount,
                   net_mf_amount, net_mf_vol
            FROM money_flow_full
            WHERE stock_code = '{code}'
            ORDER BY trade_date DESC LIMIT 60
        """).fetchall()

        # 估值数据 (最新)
        val_row = conn.execute(f"""
            SELECT pe_ttm, pb, circ_mv
            FROM stock_valuation
            WHERE stock_code = '{code}'
            ORDER BY date DESC LIMIT 1
        """).fetchone()

        val_dict = {}
        if val_row:
            if val_row[0] and abs(float(val_row[0])) > 0:
                val_dict['ep_ttm'] = 1.0 / float(val_row[0])
            if val_row[1] and float(val_row[1]) > 0:
                val_dict['pb'] = float(val_row[1])
            if val_row[2] and float(val_row[2]) > 0:
                val_dict['ln_circ_mv'] = np.log(float(val_row[2]))

        # ROE (最新)
        roe_row = conn.execute(f"""
            SELECT roe FROM stk_fin_income
            WHERE stock_code = '{code}' AND roe IS NOT NULL AND roe != ''
            ORDER BY end_date DESC LIMIT 1
        """).fetchone()
        fin_dict = {}
        if roe_row:
            try:
                rv = float(roe_row[0])
                if rv > 0:
                    fin_dict['roe'] = rv
            except (ValueError, TypeError):
                pass

        # 基准指数数据
        bench_closes, bench_dates = _load_bench(conn, bench_code, max_days)

        return {
            'daily_rows': daily_rows,
            'limit_rows': limit_rows,
            'mf_rows': mf_rows,
            'val_dict': val_dict,
            'fin_dict': fin_dict,
            'bench_closes': bench_closes,
            'bench_dates': bench_dates,
        }

    finally:
        conn.close()


def _load_bench(conn, index_code, max_days=300):
    """加载基准指数收盘价"""
    rows = conn.execute(f"""
        SELECT date, close FROM index_daily
        WHERE index_code = '{index_code}'
        ORDER BY date DESC LIMIT {max_days}
    """).fetchall()

    if not rows:
        return None, None

    # 转为ASC
    dates   = [str(r[0])[:10] for r in rows[::-1]]
    closes  = np.array([float(r[1]) for r in rows[::-1]])

    return closes, dates


def compute_target(stock_dates, stock_closes, bench_closes, bench_dates, forward_days=20):
    """
    计算目标变量: forward_days日超额收益率。

    Args:
        stock_dates: list of date strings (ASC) — 股票交易日日期
        stock_closes: np.array — 对应收盘价
        bench_closes: np.array — 基准指数收盘价(ASC)
        bench_dates: list of date strings — 基准指数日期
        forward_days: 预测N个交易日后的收益

    Returns:
        targets: list of float — 每个可计算样本的目标值（单位%）
        target_dates: list of date str — 对应的特征日期
    """
    if bench_closes is None or len(bench_closes) == 0:
        return [], []

    # 建基准日期的查找表
    bench_dict = {}
    for idx, d in enumerate(bench_dates):
        bench_dict[d] = idx

    targets = []
    target_dates = []

    for i in range(len(stock_dates)):
        d = stock_dates[i]
        if d not in bench_dict:
            continue

        bench_idx = bench_dict[d]
        # 找forward_days个交易日后的基准
        future_bench_idx = bench_idx + forward_days
        if future_bench_idx >= len(bench_closes):
            continue

        stock_future_idx = i + forward_days
        if stock_future_idx >= len(stock_closes):
            continue

        if stock_closes[i] <= 0 or bench_closes[bench_idx] <= 0:
            continue

        # 超额收益 = (股票未来收益 - 基准未来收益) * 100
        stock_ret = stock_closes[stock_future_idx] / stock_closes[i] - 1
        bench_ret = bench_closes[future_bench_idx] / bench_closes[bench_idx] - 1

        targets.append((stock_ret - bench_ret) * 100)  # 百分数
        target_dates.append(d)

    return targets, target_dates


def load_all_for_training(stocks, start_date='2019-01-01', end_date=None):
    """
    批量加载所有股票数据用于训练。

    设计：每只股票拉完整日K，用滑动窗口批量计算特征+目标。
    避免逐样本调用compute_features（太慢），改为向量化批量计算。

    Yields:
        (code, feat_vec, target, date) tuples
    """
    conn = connect()
    try:
        # 预加载所有基准指数
        bench_cache = {}
        for ic in ['000300', '000905', '000688', '399006']:
            rows = conn.execute(f"""
                SELECT date, close FROM index_daily
                WHERE index_code = '{ic}' AND date >= '{start_date}'
                ORDER BY date ASC
            """).fetchall()
            if rows:
                bench_cache[ic] = {
                    'dates': [str(r[0])[:10] for r in rows],
                    'closes': np.array([float(r[1]) for r in rows]),
                }

        # 构建基准日期查找表
        bench_lookup = {}  # (bench_code, date) -> index in bench_closes
        for ic, bench in bench_cache.items():
            for idx, d in enumerate(bench['dates']):
                bench_lookup[(ic, d)] = idx

        end_cond = f"AND date <= '{end_date}'" if end_date else ""

        for stock_idx, stock in enumerate(stocks):
            code = stock['code']
            bench_code = stock['bench']

            # 日K线 (ASC) — 需要额外拉120天历史用于特征计算
            hist_start = '2015-01-01' if start_date > '2016-01-01' else start_date
            daily_asc = conn.execute(f"""
                SELECT date, open, close, high, low, volume, amount
                FROM stock_daily
                WHERE stock_code = '{code}' AND date >= '{hist_start}'
                {end_cond}
                ORDER BY date ASC
            """).fetchall()

            if len(daily_asc) < 150:
                continue

            stock_dates = [str(r[0])[:10] for r in daily_asc]
            stock_closes = np.array([float(r[2]) for r in daily_asc], dtype=np.float64)
            stock_opens = np.array([float(r[1]) for r in daily_asc], dtype=np.float64)
            stock_highs = np.array([float(r[3]) for r in daily_asc], dtype=np.float64)
            stock_lows  = np.array([float(r[4]) for r in daily_asc], dtype=np.float64)
            stock_vols  = np.array([float(r[5] or 0) for r in daily_asc], dtype=np.float64)
            stock_amts  = np.array([float(r[6] or 0) for r in daily_asc], dtype=np.float64)

            bench = bench_cache.get(bench_code, None)
            if bench is None:
                continue

            # 涨跌停价 (ASC)
            limit_asc = conn.execute(f"""
                SELECT date, up_limit, down_limit
                FROM stk_limit WHERE stock_code = '{code}'
                ORDER BY date ASC
            """).fetchall()
            limit_dict = {str(r[0])[:10]: (float(r[1]), float(r[2])) for r in limit_asc}

            # 资金流 — 按日期排序
            mf_rows_all = conn.execute(f"""
                SELECT trade_date, net_mf_amount
                FROM money_flow_full WHERE stock_code = '{code}'
                ORDER BY trade_date ASC
            """).fetchall()
            mf_dict = {str(r[0])[:10]: float(r[1] or 0) for r in mf_rows_all}

            # 估值 (最新)
            val_row = conn.execute(f"""
                SELECT pe_ttm, pb, circ_mv
                FROM stock_valuation WHERE stock_code = '{code}'
                ORDER BY date DESC LIMIT 1
            """).fetchone()
            val_dict = {}
            if val_row:
                if val_row[0] and abs(float(val_row[0])) > 0:
                    val_dict['ep_ttm'] = 1.0 / float(val_row[0])
                if val_row[1] and float(val_row[1]) > 0:
                    val_dict['pb'] = float(val_row[1])
                if val_row[2] and float(val_row[2]) > 0:
                    val_dict['ln_circ_mv'] = np.log(float(val_row[2]))

            # ROE
            roe_row = conn.execute(f"""
                SELECT roe FROM stk_fin_income
                WHERE stock_code = '{code}' AND roe IS NOT NULL AND roe != ''
                ORDER BY end_date DESC LIMIT 1
            """).fetchone()
            fin_dict = {}
            if roe_row:
                try:
                    rv = float(roe_row[0])
                    if rv > 0:
                        fin_dict['roe'] = rv
                except (ValueError, TypeError):
                    pass

            # ─── 批量计算特征 + 目标（向量化）─────────────────────
            n = len(daily_asc)
            returns = np.zeros(n, dtype=np.float64)
            for i in range(1, n):
                if stock_closes[i-1] > 0:
                    returns[i] = (stock_closes[i] / stock_closes[i-1]) - 1

            # 滑动窗口特征计算（从第120天开始）
            from core.features import N_FEATURES, FEAT_NAMES

            for i in range(120, n):
                d = stock_dates[i]

                # 检查是否在训练时间范围内
                if d < start_date:
                    continue
                if end_date and d > end_date:
                    continue

                # 计算目标（需要i+20存在）
                if i + 20 >= n:
                    continue
                if (bench_code, d) not in bench_lookup:
                    continue
                bi = bench_lookup[(bench_code, d)]
                if bi + 20 >= len(bench['closes']):
                    continue
                if stock_closes[i] <= 0 or bench['closes'][bi] <= 0:
                    continue

                target = (stock_closes[i+20] / stock_closes[i] - 1
                         - bench['closes'][bi+20] / bench['closes'][bi]) * 100

                # ─── 计算特征（用i之前的数据）─────────────────────
                c = stock_closes[:i+1]  # [:=i] inclusive
                o = stock_opens[:i+1]
                h = stock_highs[:i+1]
                l = stock_lows[:i+1]
                v = stock_vols[:i+1]
                a = stock_amts[:i+1]
                ret_slice = returns[:i+1]
                m = len(c)

                lc = c[-1]

                # Momentum (4)
                chg5  = lc/c[-6]-1 if m>=6 else 0.0
                chg10 = lc/c[-11]-1 if m>=11 else 0.0
                chg20 = lc/c[-21]-1 if m>=21 else 0.0
                chg60 = lc/c[-61]-1 if m>=61 else 0.0

                # Deviation (3)
                ma5  = np.mean(c[-5:])  if m>=5 else lc
                ma20 = np.mean(c[-20:]) if m>=20 else lc
                ma60 = np.mean(c[-60:]) if m>=60 else lc
                d5_ma   = (lc/ma5)-1 if ma5>0 else 0.0
                d20_ma  = (lc/ma20)-1 if ma20>0 else 0.0
                d60_ma  = (lc/ma60)-1 if ma60>0 else 0.0

                # Volatility (3)
                std10 = float(np.std(ret_slice[-10:]))*np.sqrt(252) if m>=10 else 0.0
                std20 = float(np.std(ret_slice[-20:]))*np.sqrt(252) if m>=20 else 0.0
                atr20 = 0.0
                if m >= 21:
                    trs = np.maximum(h[-20:] - l[-20:],
                           np.maximum(np.abs(h[-20:] - c[-21:-1]),
                                      np.abs(l[-20:] - c[-21:-1])))
                    atr20 = float(np.mean(trs)) / lc

                # Volume (3)
                vol_ratio5 = v[-1]/np.mean(v[-6:-1]) if m>=6 and np.mean(v[-6:-1])>0 else 1.0
                vol_trend = 0.0
                if m >= 20:
                    vol_trend = np.mean(v[-5:])/(np.mean(v[-20:-15])+1e-15)-1
                amount_rank = 0.5
                if m >= 60 and np.max(a[-60:-1])>np.min(a[-60:-1]):
                    amount_rank = (a[-1]-np.min(a[-60:-1]))/(np.max(a[-60:-1])-np.min(a[-60:-1])+1e-15)

                # Position (4)
                pos20 = 0.5
                if m >= 20:
                    lo20, hi20 = np.min(c[-20:]), np.max(c[-20:])
                    pos20 = (lc-lo20)/(hi20-lo20+1e-15) if hi20>lo20 else 0.5
                pos60 = 0.5
                if m >= 60:
                    lo60, hi60 = np.min(c[-60:]), np.max(c[-60:])
                    pos60 = (lc-lo60)/(hi60-lo60+1e-15) if hi60>lo60 else 0.5

                near_up = 0.0
                near_dn = 0.0
                lim = limit_dict.get(d)
                if lim:
                    if lim[0] > 0: near_up = (lc - lim[0])/lc
                    if lim[1] > 0: near_dn = (lc - lim[1])/lc

                # Trend (2)
                ma10 = np.mean(c[-10:]) if m>=10 else lc
                ma_alignment = int(ma5>ma10 and ma10>ma20 and ma20>ma60)
                higher_high = int(lc > hi20*0.98) if m >= 20 else 0

                # Valuation (3)
                ep_ttm = val_dict.get('ep_ttm', 0.0)
                pb_val = val_dict.get('pb', 1.0)
                ln_mv = val_dict.get('ln_circ_mv', 22.0)

                # Fund flow (3) — look up recent dates
                mf_net_5d = 0.0
                mf_net_20d = 0.0
                mf_ratio_val = 0.0
                recent_mf = []
                for j in range(i, max(-1, i-60), -1):
                    dd = stock_dates[j]
                    if dd in mf_dict:
                        recent_mf.append(mf_dict[dd])
                    if len(recent_mf) >= 20:
                        break
                if len(recent_mf) >= 5:
                    mf_net_5d = sum(recent_mf[:5])
                if len(recent_mf) >= 20:
                    mf_net_20d = sum(recent_mf[:20])
                if m >= 5 and np.mean(a[-5:]) > 0:
                    mf_ratio_val = (sum(recent_mf[:5]) if recent_mf else 0)*1e4 / (np.mean(a[-5:])+1e-15)

                # Reversal (3)
                dn_streak = 0
                for j in range(len(ret_slice)-1, max(-1, len(ret_slice)-21), -1):
                    if ret_slice[j] < 0: dn_streak += 1
                    else: break

                up_ratio10 = float(np.sum(ret_slice[-10:]>0))/10.0 if m>=10 else 0.5
                vol_accel = 0.0
                if m >= 15:
                    sr = float(np.std(ret_slice[-5:]))
                    se = float(np.std(ret_slice[-10:-5]))
                    vol_accel = (sr-se)/(se+1e-15)

                feat_vec = np.array([
                    chg5, chg10, chg20, chg60,
                    d5_ma, d20_ma, d60_ma,
                    std10, std20, atr20,
                    vol_ratio5, vol_trend, amount_rank,
                    pos20, pos60, near_up, near_dn,
                    ma_alignment, higher_high,
                    ep_ttm, pb_val, ln_mv,
                    mf_net_5d, mf_net_20d, mf_ratio_val,
                    dn_streak, up_ratio10, vol_accel,
                ], dtype=np.float64)

                if not np.any(np.isnan(feat_vec)) and not np.any(np.isinf(feat_vec)):
                    yield (code, feat_vec, target, d)

    finally:
        conn.close()
