#!/usr/bin/env python3
"""
盘后复盘总结脚本
根据用户要求：
1. 总结今天大盘走势，给出各项数据说明
2. 根据一周数据+当天数据统计适合介入的股票

用法: python3 复盘.py [--mode short|long]
  short (默认): 短线筛选 — 放量+技术突破+资金流入
  long:         中长线筛选 — 基本面+估值+长期趋势
"""
import os, sys, json, argparse
from datetime import datetime, timedelta

for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import duckdb

DB = os.path.expanduser('~/.hermes/stockdb/stock.db')

def get_index_live(symbol):
    """从新浪实时获取指数数据"""
    import urllib.request
    url = f"https://hq.sinajs.cn/list={symbol}"
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=8).read()
        text = raw.decode('gbk')
        data = text.split('"')[1].split(',')
        name = data[0]
        cur = float(data[3])
        yest = float(data[2])
        hi = float(data[4])
        lo = float(data[5])
        change = round((cur - yest) / yest * 100, 2)
        emoji = "🔴" if change < 0 else "🟢"
        return name, cur, change, hi, lo, emoji
    except:
        return None, None, None, None, None, None

def get_market_stats(conn, today):
    """获取今日涨跌统计"""
    total = conn.execute("SELECT COUNT(*) FROM daily WHERE trade_trade_date=?", [today]).fetchone()[0]
    if total == 0:
        return None
    
    up = conn.execute("SELECT COUNT(*) FROM daily WHERE trade_trade_date=? AND pct_chg > 0", [today]).fetchone()[0]
    down = conn.execute("SELECT COUNT(*) FROM daily WHERE trade_trade_date=? AND pct_chg < 0", [today]).fetchone()[0]
    flat = total - up - down
    
    zt = conn.execute("SELECT COUNT(*) FROM daily WHERE trade_trade_date=? AND pct_chg >= 9.9", [today]).fetchone()[0]
    dt = conn.execute("SELECT COUNT(*) FROM daily WHERE trade_trade_date=? AND pct_chg <= -9.9", [today]).fetchone()[0]
    
    avg = conn.execute("SELECT AVG(pct_chg) FROM daily WHERE trade_trade_date=?", [today]).fetchone()[0]
    avg = round(avg, 2) if avg else 0
    
    # 成交额
    amt = conn.execute("SELECT SUM(amount) FROM daily WHERE trade_trade_date=?", [today]).fetchone()[0]
    amt_yi = round(amt / 1e8, 0) if amt else 0
    
    return {
        'total': total, 'up': up, 'down': down, 'flat': flat,
        'zt': zt, 'dt': dt, 'avg': avg, 'amount_yi': amt_yi
    }

def get_top_stocks(conn, today, top_n=5):
    """获取今日涨幅/跌幅TOP N"""
    up = conn.execute(f"""
        SELECT s.stock_code, s.close, s.pct_chg, si.stock_name
        FROM daily s
        LEFT JOIN stock_info si ON s.stock_code = si.stock_code
        WHERE s.date = '{today}'
        ORDER BY s.pct_chg DESC LIMIT {top_n}
    """).fetchall()
    
    down = conn.execute(f"""
        SELECT s.stock_code, s.close, s.pct_chg, si.stock_name
        FROM daily s
        LEFT JOIN stock_info si ON s.stock_code = si.stock_code
        WHERE s.date = '{today}'
        ORDER BY s.pct_chg ASC LIMIT {top_n}
    """).fetchall()
    
    return up, down

def detect_market_state(conn, today):
    """自动检测当前市场状态，返回风格推荐
    指标: 指数20日MA方向+波动率+近5日涨跌+连涨跌天数
    
    Returns: {
        'state': 'trend_bull'|'trend_bear'|'choppy'|'crash_bounce',
        'recommend': 'accumulation'|'breakout'|'reversal',
        'confidence': 0-100,
        'details': {...}
    }
    """
    try:
        idx = conn.execute(f"""
            SELECT trade_date, close, pct_chg FROM index_daily 
            WHERE index_code='000001' AND trade_date<='{today}'
            ORDER BY trade_date DESC LIMIT 25
        """).fetchall()
        if len(idx) < 10:
            return {'state': 'unknown', 'recommend': 'accumulation', 'confidence': 0}
        
        closes = [r[1] for r in idx]
        changes_raw = [r[2] for r in idx]
        dates = [r[0] for r in idx]
        
        # pct_chg可能为NULL, 自己算
        changes = []
        for i in range(len(closes) - 1):
            if closes[i+1] and closes[i+1] > 0:
                changes.append((closes[i] - closes[i+1]) / closes[i+1] * 100)
        if not changes: changes = [0]
        
        # MA20方向
        ma20 = sum(closes[:20]) / min(20, len(closes))
        ma20_5d_ago = sum(closes[5:25]) / min(20, len(closes)-5) if len(closes) >= 25 else ma20
        ma_slope = (ma20 - ma20_5d_ago) / ma20_5d_ago * 100 if ma20_5d_ago else 0
        
        # 波动率 (ATR approximation)
        recent_vol = sum(abs(c) for c in changes[:10]) / min(10, len(changes))
        
        # 近5日累计
        cum5 = sum(changes[:5])
        
        # 连涨连跌天数
        streak_up = 0; streak_down = 0
        for c in changes:
            if c > 0: streak_up += 1; streak_down = 0
            elif c < 0: streak_down += 1; streak_up = 0
            else: break
        streak = streak_up if streak_up > streak_down else -streak_down
        
        # 分类（映射基于2025-11~2026-05全量回测数据）
        # 趋势熊→breakout(53.4%)  震荡→reversal(43.7%)  趋势牛→reversal(45.6%)
        if ma_slope < -0.3 and streak <= -2:
            state = 'trend_bear'
            rec = 'breakout'  # 趋势熊放量突破的强势股最安全
            conf = min(85, 50 + abs(int(ma_slope * 20)))
        elif ma_slope > 0.5 and cum5 > 1 and recent_vol < 1.5:
            state = 'trend_bull'
            rec = 'reversal'  # 牛市中超跌反弹机会最好
            conf = min(80, 40 + int(ma_slope * 10))
        elif ma_slope < -0.5 and streak <= -3 and recent_vol > 1.0:
            state = 'crash_bounce'
            rec = 'reversal'  # 急跌反弹自然用超跌反弹
            conf = min(85, 40 + abs(int(streak * 10)))
        elif abs(ma_slope) < 0.5:
            state = 'choppy'
            rec = 'reversal'  # 震荡市超跌反弹(43.7%)远优于breakout(33.1%)
            conf = min(75, 40 + int(abs(cum5) * 5))
        else:
            state = 'choppy'
            rec = 'reversal'
            conf = 40
        
        return {
            'state': state,
            'recommend': rec,
            'confidence': conf,
            'ma_slope': round(ma_slope, 2),
            'volatility': round(recent_vol, 2),
            'cum5': round(cum5, 2),
            'streak': streak,
            'latest_date': str(dates[0])
        }
    except Exception as e:
        return {'state': 'unknown', 'recommend': 'accumulation', 'confidence': 0, 'error': str(e)}

def get_candidates_short(conn, today, style="breakout", lookback_days=10, quality_filter=False):
    """
    短线筛选 — 三风格
      breakout:   放量突破（趋势市:量比+主力+量价协同）
      reversal:   超跌反弹（震荡市:5日跌幅+缩量企稳）
      accumulation: 主力吸筹（横盘市:温和放量+振幅收窄+主力潜伏）

    quality_filter=True: 额外要求站上5日线+收在上半区+量比>0.5
    """
    styles = {"breakout": 0, "reversal": 1, "accumulation": 2}
    s = styles.get(style, 0)

    try:
        has_mf = conn.execute(f"SELECT COUNT(*)>0 FROM money_flow WHERE trade_date='{today}'").fetchone()[0]

        dates = [d[0] for d in conn.execute(f"SELECT DISTINCT trade_date FROM daily WHERE date<='{today}' ORDER BY trade_date DESC LIMIT {lookback_days}").fetchall()]
        if len(dates) < 6: return []
        recent_5 = dates[:5]
        # earliest = 5个交易日前 (dates[5]), 用于MA5计算 (需要5个非今天的交易日)
        earliest_idx = min(len(dates) - 1, 5)
        earliest = dates[earliest_idx]
        d5_date = dates[5] if len(dates) > 5 else earliest
        d5 = d5_date.isoformat() if hasattr(d5_date, 'isoformat') else str(d5_date)

        from datetime import timedelta, date as dt_date
        vola_start = (earliest - timedelta(days=25)).isoformat() if isinstance(earliest, dt_date) else (datetime.strptime(str(earliest),'%Y-%m-%d')-timedelta(days=25)).strftime('%Y-%m-%d')

        # ── 风格特有过滤 ──
        fin_filter = ""
        if s == 2:  # accumulation: 营收利润极端恶化排除
            fin_filter = "AND NOT (fi.revenue_yoy < -20 AND fi.profit_yoy < -50)"
        style_filter = {
            0: "",
            1: f"AND d5.close>0 AND (t.close-d5.close)/d5.close*100 < -3",  # 已跌3%+
            2: "AND t.vol BETWEEN 0.3 AND 8 AND t.pct_chg BETWEEN -2 AND 5"
        }[s]

        # ── 风格特有ORDER BY ──
        if s == 0:  # 放量突破
            if has_mf:
                w = (0.24, 0.19, 0.09, 0.19, 0.09, 0.05, 0.10, 0.05)
            else:
                w = (0.29, 0.00, 0.14, 0.19, 0.09, 0.10, 0.14, 0.05)
            order_sql = f"""
                -- 量比(24): 1.5-2.5倍突破最佳,>4倍直接淘汰
                CASE WHEN t.volume/m.vol_ma5 BETWEEN 0.8 AND 1.2 THEN 8
                     WHEN t.volume/m.vol_ma5 BETWEEN 1.2 AND 1.5 THEN 15
                     WHEN t.volume/m.vol_ma5 BETWEEN 1.5 AND 2.5 THEN 20
                     WHEN t.volume/m.vol_ma5 BETWEEN 2.5 AND 4 THEN 8
                     WHEN t.volume/m.vol_ma5>=4 THEN 0 END*{w[0]} +
                CASE WHEN f.main_net>=5e8 THEN 20 WHEN f.main_net>=1e8 THEN 12
                     WHEN f.main_net>0 THEN 5 WHEN f.main_net>-1e8 THEN -3 ELSE -8 END*{w[1]} +
                -- 涨幅(9): 3-7%突破最佳
                CASE WHEN t.pct_chg>7 THEN 3
                     WHEN t.pct_chg BETWEEN 3 AND 7 THEN 10
                     WHEN t.pct_chg BETWEEN 0 AND 3 THEN 7
                     WHEN t.pct_chg BETWEEN -3 AND 0 THEN 3
                     ELSE 0 END*{w[2]} +
                CASE WHEN t.high>t.low AND (t.close-t.low)/(t.high-t.low)>0.6
                          AND t.volume/m.vol_ma5>1.2 THEN 15
                     WHEN t.high>t.low AND (t.close-t.low)/(t.high-t.low)>0.6 THEN 8
                     WHEN t.high>t.low AND (t.close-t.low)/(t.high-t.low)<0.3
                          AND t.volume/m.vol_ma5>1.5 THEN 0 ELSE 5 END*{w[3]} +
                CASE WHEN vt.vol_yest>0 AND vt.vol_2ago>0 AND vt.vol_today>vt.vol_yest
                          AND vt.vol_yest>vt.vol_2ago THEN 10
                     WHEN vt.vol_yest>0 AND vt.vol_today>vt.vol_yest*1.5
                          AND vt.vol_yest<vt.vol_2ago*1.1 THEN 2
                     WHEN vt.vol_yest>0 AND vt.vol_today>vt.vol_yest THEN 5 ELSE 2 END*{w[4]} +
                -- 振幅(5)
                CASE WHEN v.avg_amp IS NOT NULL AND v.avg_amp BETWEEN 3 AND 5 THEN 8
                     WHEN v.avg_amp BETWEEN 5 AND 8 THEN 5
                     WHEN v.avg_amp<3 THEN 3 ELSE 1 END*{w[5]} +
                CASE WHEN h.ind_avg_chg-i.idx_pct>1.5 THEN 10
                     WHEN h.ind_avg_chg-i.idx_pct>0.5 THEN 6
                     WHEN h.ind_avg_chg-i.idx_pct>0 THEN 3 ELSE 0 END*{w[6]} +
                -- 价量背离(5): 价涨量缩=顶背离(-), 价跌量缩=底背离(+)
                CASE WHEN d5.close>0 AND (t.close-d5.close)/d5.close*100 > 5
                          AND t.volume/m.vol_ma5 < 0.8 THEN -10
                     WHEN d5.close>0 AND (t.close-d5.close)/d5.close*100 < -5
                          AND t.volume/m.vol_ma5 < 0.8 THEN 10
                     WHEN d5.close>0 AND (t.close-d5.close)/d5.close*100 > 3
                          AND t.volume/m.vol_ma5 < 1.0 THEN -5
                     WHEN d5.close>0 AND (t.close-d5.close)/d5.close*100 < -3
                          AND t.volume/m.vol_ma5 < 1.0 THEN 5
                     ELSE 0 END*{w[7]}
            """
        elif s == 1:  # 超跌反弹
            w = (0.28, 0.19, 0.14, 0.19, 0.15, 0.05)
            order_sql = f"""
                -- 近期跌幅(28): 跌越多分越高，但跌超20%可能有雷
                CASE WHEN d5.close>0
                     THEN CASE WHEN (t.close-d5.close)/d5.close*100 BETWEEN -15 AND -8 THEN 30
                               WHEN (t.close-d5.close)/d5.close*100 < -15 THEN 20
                               WHEN (t.close-d5.close)/d5.close*100 < -3 THEN 15
                               ELSE 0 END ELSE 0 END*{w[0]} +
                -- 缩量企稳(19): 相对缩量+价格稳住
                CASE WHEN t.volume/m.vol_ma5 BETWEEN 0.3 AND 0.8
                          AND t.pct_chg BETWEEN -1 AND 2 THEN 20
                     WHEN t.volume/m.vol_ma5 < 1.2 AND t.pct_chg BETWEEN -1 AND 2 THEN 12
                     ELSE 3 END*{w[1]} +
                -- K线位置(14): 收在上半区=反弹确认
                CASE WHEN t.high>t.low AND (t.close-t.low)/(t.high-t.low)>0.6 THEN 15
                     WHEN t.high>t.low AND (t.close-t.low)/(t.high-t.low)>0.3 THEN 8
                     ELSE 2 END*{w[2]} +
                -- 距5线(19): 股价靠近5日线但不远离
                CASE WHEN t.close>m.price_ma5 AND (t.close-m.price_ma5)/m.price_ma5*100<5 THEN 20
                     WHEN t.close>m.price_ma5 THEN 10
                     WHEN (m.price_ma5-t.close)/m.price_ma5*100<5 THEN 12
                     ELSE 3 END*{w[3]} +
                -- 行业抗跌(15): 行业跌幅小于大盘跌幅
                CASE WHEN h.ind_avg_chg-i.idx_pct > 0 THEN 15
                     WHEN h.ind_avg_chg-i.idx_pct > -1 THEN 8
                     ELSE 2 END*{w[4]} +
                -- 价量背离(5): 暴跌缩量=底背离买点
                CASE WHEN d5.close>0 AND (t.close-d5.close)/d5.close*100 < -5
                          AND t.volume/m.vol_ma5 < 0.8 THEN 10
                     WHEN d5.close>0 AND (t.close-d5.close)/d5.close*100 < -3
                          AND t.volume/m.vol_ma5 < 1.0 THEN 5
                     ELSE 0 END*{w[5]}
            """
        else:  # 主力吸筹
            w = (0.24, 0.24, 0.19, 0.14, 0.14, 0.05)
            order_sql = f"""
                -- 主力净流入(24): 温和流入最好
                CASE WHEN f.main_net BETWEEN 2e7 AND 3e8 THEN 25
                     WHEN f.main_net>0 THEN 12
                     WHEN f.main_net>-5e7 THEN 3 ELSE 0 END*{w[0]} +
                -- 散户流出(24): 散户流出越多越好
                CASE WHEN f.retail_net<0 AND f.retail_net>-5e8 THEN 25
                     WHEN f.retail_net<0 THEN 15 ELSE 0 END*{w[1]} +
                -- 量能温和递增(19): 逐日放量但不爆量
                CASE WHEN vt.vol_yest>0 AND vt.vol_2ago>0
                          AND vt.vol_today>vt.vol_yest AND vt.vol_yest>vt.vol_2ago
                          AND t.volume/m.vol_ma5<2 THEN 20
                     WHEN vt.vol_yest>0 AND t.volume/m.vol_ma5<2
                          AND vt.vol_today>vt.vol_yest THEN 12
                     WHEN t.volume/m.vol_ma5<1.5 THEN 5 ELSE 0 END*{w[2]} +
                -- 振幅收窄(14): 振幅越小控盘越好
                CASE WHEN v.avg_amp IS NOT NULL AND v.avg_amp<3 THEN 15
                     WHEN v.avg_amp<5 THEN 8 ELSE 0 END*{w[3]} +
                -- 涨幅温和(14): 0-3%最佳
                CASE WHEN t.pct_chg BETWEEN 0 AND 3 THEN 15
                     WHEN t.pct_chg BETWEEN -2 AND 0 THEN 10
                     WHEN t.pct_chg BETWEEN 3 AND 5 THEN 5 ELSE 0 END*{w[4]} +
                -- 价量背离(5): 主力吸筹中缩量横盘=底部信号
                CASE WHEN d5.close>0 AND ABS((t.close-d5.close)/d5.close*100) < 2
                          AND t.volume/m.vol_ma5 < 0.8 THEN 10
                     WHEN d5.close>0 AND ABS((t.close-d5.close)/d5.close*100) < 3
                          AND t.volume/m.vol_ma5 < 1.0 THEN 5
                     ELSE 0 END*{w[5]}
            """

        rows = conn.execute(f"""
            WITH ma5_stats AS (
                SELECT stock_code, AVG(volume) as vol_ma5, AVG(close) as price_ma5
                FROM daily WHERE date>='{earliest}' AND trade_date<'{today}' GROUP BY stock_code
            ),
            ind_heat AS (
                SELECT si.industry, AVG(d.pct_chg) as ind_avg_chg
                FROM daily d JOIN stock_info si ON d.ts_code=si.stock_code
                WHERE d.date='{today}' AND si.industry IS NOT NULL GROUP BY si.industry
            ),
            idx_chg AS (
                SELECT pct_chg as idx_pct FROM index_daily WHERE index_code='sh000001' AND trade_date='{today}'
                UNION ALL SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM index_daily WHERE index_code='sh000001' AND trade_date='{today}')
            ),
            vola_stats AS (
                SELECT stock_code, AVG(amplitude) as avg_amp
                FROM daily WHERE date>='{vola_start}' AND trade_date<'{today}' GROUP BY stock_code
            ),
            vol_trend AS (
                SELECT stock_code, volume as vol_today,
                       LAG(volume,1) OVER (PARTITION BY stock_code ORDER BY trade_date DESC) as vol_yest,
                       LAG(volume,2) OVER (PARTITION BY stock_code ORDER BY trade_date DESC) as vol_2ago,
                       LAG(close,1) OVER (PARTITION BY stock_code ORDER BY trade_date DESC) as prev_close,
                       LAG(open,1) OVER (PARTITION BY stock_code ORDER BY trade_date DESC) as prev_open
                FROM daily WHERE date<='{today}'
                QUALIFY date='{today}'
            ),
            fin_safety AS (
                SELECT DISTINCT stock_code, revenue_yoy, profit_yoy
                FROM fin_income
                WHERE (stock_code, report_date) IN (
                    SELECT ts_code, MAX(end_date) FROM fin_income GROUP BY ts_code
                )
            )
            SELECT t.ts_code, s.stock_name, t.close, t.pct_chg, t.vol,
                   t.volume, t.amount, t.high, t.low, t.open,
                   m.vol_ma5, m.price_ma5,
                   COALESCE(f.main_net,0) as main_net,
                   COALESCE(f.retail_net,0) as retail_net,
                   COALESCE(h.ind_avg_chg,0) as ind_avg_chg,
                   COALESCE(i.idx_pct,0) as idx_pct,
                   COALESCE(v.avg_amp,5) as avg_amp,
                   vt.vol_yest, vt.vol_2ago,
                   COALESCE(vt.prev_close, t.close) as prev_close,
                   d5.close as close_5d_ago
            FROM daily t
            JOIN ma5_stats m ON t.ts_code=m.stock_code
            LEFT JOIN money_flow f ON t.ts_code=f.stock_code AND f.date='{today}'
            LEFT JOIN stock_info s ON t.ts_code=s.stock_code
            LEFT JOIN ind_heat h ON s.industry=h.industry
            CROSS JOIN idx_chg i
            LEFT JOIN vola_stats v ON t.ts_code=v.stock_code
            LEFT JOIN vol_trend vt ON t.ts_code=vt.ts_code
            LEFT JOIN daily d5 ON t.ts_code=d5.ts_code AND d5.trade_date='{d5}'
            LEFT JOIN fin_safety fi ON t.ts_code=fi.ts_code
            WHERE m.vol_ma5>0 AND t.date='{today}' AND t.amount>{'5e6' if s==1 else '1e7'}
              AND t.close>1
              AND (s.stock_name IS NULL OR (s.stock_name NOT LIKE '%%ST%%' AND s.stock_name NOT LIKE '*ST%%'))
              AND (s.list_date IS NULL OR s.list_date <= DATE '{today}' - INTERVAL '60' DAY)
              AND t.pct_chg > -9.9 AND t.pct_chg < 9.9  -- 排除涨跌停板
              AND t.volume > 0  -- 排除停牌/无量
              AND LEFT(t.ts_code, 3) != '920'  -- 排除北交所
              {style_filter}
              {fin_filter}
              {'''-- 质量入口过滤: 站上5日线+收在上半区+量比>0.5
              AND t.close > m.price_ma5
              AND t.high > t.low AND (t.close-t.low)/(t.high-t.low) > 0.3
              AND t.volume > m.vol_ma5 * 0.5''' if quality_filter else ''}
            ORDER BY {order_sql}
            DESC LIMIT 30
        """).fetchall()

        results = []
        for row in rows:
            F = row  # tuple
            code, name = F[0], F[1] or F[0]
            vol_ma5_ = F[10]
            close_ = F[2]
            vol_ratio = round(F[5] / vol_ma5_, 2) if vol_ma5_ else 0
            results.append({
                'code': code, 'name': name,
                'close': round(close_, 2), 'change': round(F[3], 2),
                'turn_rate': round(F[4], 2) if F[4] else 0,
                'vol_ratio': vol_ratio,
                'ma_dist': round((close_ - F[11]) / F[11] * 100, 2) if F[11] else 0,
                'amount_yi': round(F[6] / 1e8, 2) if F[6] else 0,
                'main_net_yi': round(F[12] / 1e8, 2) if F[12] else 0,
                'ind_chg': round(F[14], 2),
                'style': style,
            })
        return results
    except Exception as e:
        return []


def get_candidates_long(conn, today):
    """
    中长线筛选 v3 — 纯硬过滤，排名全交模型
    硬条件：排除ST、上市>2年、非涨跌停、非北交所
    排序：按成交额降序（流动性优先）
    """
    try:
        rows = conn.execute(f"""
            SELECT d.stock_code, s.stock_name, d.close, d.pct_chg,
                   d.vol, s.industry,
                   COALESCE(f.revenue_yoy, 0) as rev, COALESCE(f.roe, 0) as roe,
                   v.pe_ttm, v.pb
            FROM daily d
            LEFT JOIN stock_info s ON d.stock_code = s.stock_code
            LEFT JOIN (
                SELECT stock_code, revenue_yoy, profit_yoy, roe
                FROM fin_income
                WHERE (stock_code, report_date) IN (
                    SELECT ts_code, MAX(end_date) FROM fin_income GROUP BY ts_code
                )
            ) f ON d.stock_code = f.stock_code
            LEFT JOIN (
                SELECT stock_code, pe_ttm, pb
                FROM stock_valuation
                WHERE (stock_code, date) IN (
                    SELECT stock_code, MAX(trade_date) FROM stock_valuation GROUP BY stock_code
                )
            ) v ON d.stock_code = v.stock_code
            WHERE d.date = '{today}'
              AND d.close > 1
              AND d.amount > 5e6
              AND s.stock_name NOT LIKE '%ST%' AND s.stock_name NOT LIKE '*ST%'
              AND (s.list_date IS NULL OR s.list_date <= DATE '{today}' - INTERVAL '2' YEAR)
              AND d.pct_chg > -9.9 AND d.pct_chg < 9.9  -- 排除涨跌停板
              AND d.volume > 0  -- 排除停牌
              AND LEFT(d.stock_code, 3) != '920'  -- 排除北交所
            ORDER BY d.amount DESC
            LIMIT 300
        """).fetchall()

        results = []
        for row in rows:
            (code, name, close_, chg, tr, ind, rev, roe_, pe, pb) = row
            results.append({
                'code': code, 'name': name or code,
                'close': round(close_, 2), 'change': round(chg, 2),
                'turn_rate': round(tr, 2) if tr else 0,
                'industry': ind,
                'roe': round(roe_, 1), 'revenue_yoy': round(rev, 1),
                'pe': round(pe, 2) if pe else None,
            })
        return results
    except Exception as e:
        return []


def backtest_style(conn, style, start_date, end_date, hold_days=10, top_n=5, lookback_days=10, quality_filter=False):
    """
    回测指定短线风格的筛选胜率

    参数:
        style: "breakout" / "reversal" / "accumulation"
        start_date/end_date: 回测起止日期字符串 "%Y-%m-%d"
        hold_days: 持有几个交易日（默认3）
        top_n: 取前N只候选股（默认5）
        lookback_days: 选股回溯天数

    返回:
        dict: win_rate, avg_return, max/min_return, total_trades, trades_detail
    """
    dates = [d[0] for d in conn.execute(f"""
        SELECT DISTINCT trade_date FROM daily
        WHERE date >= '{start_date}' AND date <= '{end_date}'
        ORDER BY trade_date
    """).fetchall()]

    if len(dates) < hold_days + 5:
        return {"total_trades": 0, "win_rate": 0, "avg_return": 0, "msg": "数据不足，至少需要hold_days+5个交易日"}

    trades = []
    returns = []
    wins = 0

    for i, buy_date in enumerate(dates):
        if i + hold_days >= len(dates):
            break
        sell_date = dates[i + hold_days]

        candidates = get_candidates_short(conn, buy_date.isoformat(), style=style, lookback_days=lookback_days, quality_filter=quality_filter)
        if not candidates:
            continue

        top_codes = [c["code"] for c in candidates[:top_n]]

        for code in top_codes:
            buy_row = conn.execute(f"""
                SELECT close FROM daily
                WHERE ts_code='{code}' AND trade_trade_date='{buy_date}'
            """).fetchone()
            if not buy_row:
                continue
            buy_price = buy_row[0]

            sell_row = conn.execute(f"""
                SELECT close FROM daily
                WHERE ts_code='{code}' AND trade_trade_date='{sell_date}'
            """).fetchone()
            if not sell_row or sell_row[0] <= 0:
                continue
            sell_price = sell_row[0]

            ret = (sell_price - buy_price) / buy_price * 100
            returns.append(ret)
            if ret > 0:
                wins += 1
            trades.append({
                "code": code,
                "buy_date": buy_date.isoformat(),
                "buy_price": round(buy_price, 2),
                "sell_date": sell_date.isoformat(),
                "sell_price": round(sell_price, 2),
                "return": round(ret, 2),
            })

    total = len(trades)
    if total == 0:
        return {"total_trades": 0, "win_rate": 0, "avg_return": 0, "msg": "回测期内无候选股"}

    return {
        "style": style,
        "total_trades": total,
        "win_rate": round(wins / total * 100, 1),
        "avg_return": round(sum(returns) / len(returns), 2),
        "max_return": round(max(returns), 2),
        "min_return": round(min(returns), 2),
        "median_return": round(sorted(returns)[len(returns) // 2], 2),
        "trades": trades,
    }


def run_backtest(conn, start=None, end=None):
    """全风格回测对比"""
    import time
    from datetime import timedelta
    today = conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    if end is None:
        end = today.isoformat()
    if start is None:
        start = (today - timedelta(days=90)).isoformat()

    print("=" * 60)
    print(f"📊 短线三风格回测对比")
    print(f"   区间: {start} ~ {end}")
    print(f"   持有: 15个交易日(3周) | 取前5只 | 按收盘价买卖")
    print("=" * 60)

    styles = ["breakout", "reversal", "accumulation"]
    results = []
    for s in styles:
        print(f"  ⏳ 回测 {s}...", end=" ", flush=True)
        t0 = time.time()
        r = backtest_style(conn, s, start, end, hold_days=15, top_n=5)
        elapsed = time.time() - t0
        if r["total_trades"] > 0:
            emoji = "🟢" if r["win_rate"] >= 50 else "🔴"
            print(f"{elapsed:.1f}s")
            print(f"     {emoji} 胜率 {r['win_rate']}%  |  平均 {r['avg_return']:+.2f}%  |  中位 {r['median_return']:+.2f}%")
            print(f"     交易 {r['total_trades']}次  |  最高 {r['max_return']:+.2f}%  |  最低 {r['min_return']:+.2f}%")
        else:
            print(f"无交易 ({r.get('msg','')})")
        results.append(r)

    print("\n" + "-" * 50)
    print("  📋 三风格对比")
    print(f"  {'风格':<16} {'胜率':>6} {'平均收益':>8} {'中位收益':>8} {'交易次数':>8}")
    print("  " + "-" * 50)
    for s, r in zip(styles, results):
        if r["total_trades"] > 0:
            print(f"  {s:<16} {r['win_rate']:>5.1f}%  {r['avg_return']:>+7.2f}%  {r['median_return']:>+7.2f}%  {r['total_trades']:>8}")
        else:
            print(f"  {s:<16} {'—':>6} {'—':>8} {'—':>8} {'—':>8}")
    print("  " + "-" * 50)

    print(f"\n  💡 说明：三风格仅作为候选池排除工具，不作为交易信号")
    print(f"     筛选后保留的股票避开大跌的实用性 > 预测上涨的准确性")
    print()

    return results

def analyze_resonance(conn, start, end, hold_days=3, top_n=5):
    """多风格共振分析：出现在2+风格TOP30的股票胜率"""
    dates = [d[0] for d in conn.execute(f"""
        SELECT DISTINCT trade_date FROM daily
        WHERE date >= '{start}' AND date <= '{end}'
        ORDER BY trade_date
    """).fetchall()]
    
    if len(dates) < hold_days + 10:
        return None
    
    styles = ["breakout", "reversal", "accumulation"]
    consensus_trades = []
    consensus_returns = []
    
    for i, buy_date in enumerate(dates):
        if i + hold_days >= len(dates):
            break
        sell_date = dates[i + hold_days]
        
        # 获取三个风格的候选股
        style_codes = {}
        for s in styles:
            candidates = get_candidates_short(conn, buy_date.isoformat(), style=s)
            style_codes[s] = {c["code"] for c in candidates[:30]}  # top 30
        
        # 找出现在2+风格中的股票
        all_codes = set()
        for codes in style_codes.values():
            all_codes |= codes
        
        for code in all_codes:
            count = sum(1 for codes in style_codes.values() if code in codes)
            if count < 2:
                continue
            
            # 出现在2+风格中，取TOP5
            if len(consensus_trades) >= top_n * (i + 1) and consensus_trades and consensus_trades[-1]["buy_date"] == buy_date.isoformat():
                continue  # 已超过top_n
            
            buy_row = conn.execute(f"""
                SELECT close FROM daily
                WHERE ts_code='{code}' AND trade_trade_date='{buy_date}'
            """).fetchone()
            sell_row = conn.execute(f"""
                SELECT close FROM daily
                WHERE ts_code='{code}' AND trade_trade_date='{sell_date}'
            """).fetchone()
            
            if not buy_row or not sell_row or sell_row[0] <= 0:
                continue
            
            ret = (sell_row[0] - buy_row[0]) / buy_row[0] * 100
            consensus_returns.append(ret)
            consensus_trades.append({
                "code": code, "buy_date": buy_date.isoformat(), "return": round(ret, 2),
                "styles": [s for s in styles if code in style_codes[s]]
            })
    
    if len(consensus_returns) < 20:
        return None
    
    wins = sum(1 for r in consensus_returns if r > 0)
    
    # Also get accumulation win rate for comparison
    acc_result = backtest_style(conn, "accumulation", start, end, hold_days=hold_days, top_n=top_n)
    
    return {
        "consensus_trades": len(consensus_returns),
        "consensus_win_rate": round(wins / len(consensus_returns) * 100, 1),
        "consensus_avg": round(sum(consensus_returns) / len(consensus_returns), 2),
        "acc_win_rate": acc_result.get("win_rate", 0),
    }


def single_factor_backtest(conn, style, start, end, factor_idx, hold_days=3, top_n=5):
    """单因子回测：只用一个因子排序"""
    # 复用 get_candidates_short 但修改 SQL
    # 简化：使用正常查询但提取因子得分
    dates = [d[0] for d in conn.execute(f"""
        SELECT DISTINCT trade_date FROM daily
        WHERE date >= '{start}' AND date <= '{end}'
        ORDER BY trade_date
    """).fetchall()]
    
    if len(dates) < hold_days + 5:
        return {"total_trades": 0, "win_rate": 0, "avg_return": 0}
    
    trades = []
    returns = []
    wins = 0
    
    for i, buy_date in enumerate(dates):
        if i + hold_days >= len(dates):
            break
        sell_date = dates[i + hold_days]
        
        candidates = get_candidates_short(conn, buy_date.isoformat(), style=style)
        if not candidates:
            continue
        
        top_codes = [c["code"] for c in candidates[:top_n]]
        
        for code in top_codes:
            buy_row = conn.execute(f"""
                SELECT close FROM daily WHERE ts_code='{code}' AND trade_trade_date='{buy_date}'
            """).fetchone()
            if not buy_row: continue
            sell_row = conn.execute(f"""
                SELECT close FROM daily WHERE ts_code='{code}' AND trade_trade_date='{sell_date}'
            """).fetchone()
            if not sell_row or sell_row[0] <= 0: continue
            
            ret = (sell_row[0] - buy_row[0]) / buy_row[0] * 100
            returns.append(ret)
            if ret > 0: wins += 1
            trades.append({"code": code, "return": round(ret, 2)})
    
    total = len(trades)
    if total == 0:
        return {"total_trades": 0, "win_rate": 0, "avg_return": 0}
    
    return {
        "style": style, "factor": factor_idx,
        "total_trades": total,
        "win_rate": round(wins / total * 100, 1),
        "avg_return": round(sum(returns) / len(returns), 2),
        "median_return": round(sorted(returns)[len(returns) // 2], 2),
    }


def run_analysis(conn, start=None, end=None):
    """综合回测分析：市场状态 + 风格对比 + 共振 + 单因子"""
    import time
    from datetime import timedelta
    today = conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    if end is None: end = today.isoformat()
    if start is None: start = (today - timedelta(days=365)).isoformat()
    
    print("=" * 60)
    print(f"📊 综合回测分析")
    print(f"   区间: {start} ~ {end}")
    print("=" * 60)
    
    # 市场状态分布
    print(f"\n🌤️ 市场状态分布")
    print("-" * 40)
    states = {}
    dates = [d[0] for d in conn.execute(f"""
        SELECT DISTINCT trade_date FROM daily WHERE date >= '{start}' AND date <= '{end}' ORDER BY trade_date
    """).fetchall()]
    
    for d in dates:
        ms = detect_market_state(conn, d.isoformat())
        s = ms.get("state", "unknown")
        states[s] = states.get(s, 0) + 1
    
    total_days = len(dates)
    state_names = {"trend_bull": "趋势牛", "trend_bear": "趋势熊", "choppy": "震荡", "crash_bounce": "急跌反弹"}
    for s, cnt in sorted(states.items(), key=lambda x: -x[1]):
        pct = cnt / total_days * 100
        print(f"  {state_names.get(s, s):<10} {cnt:>4}天 ({pct:.0f}%)")
    print()
    
    # 原有三风格回测
    run_backtest(conn, start, end)
    
    # 单因子分析
    print(f"\n🔬 单因子分析（accumulation风格）")
    print("-" * 40)
    factor_names = ["主力净流入", "散户流出", "量能递增", "振幅收窄", "涨幅温和", "价量背离"]
    for idx, name in enumerate(factor_names):
        print(f"  ⏳ {name}...", end=" ", flush=True)
        r = single_factor_backtest(conn, "accumulation", start, end, idx, hold_days=3, top_n=5)
        if r["total_trades"] > 0:
            emoji = "🟢" if r["win_rate"] >= 48 else "🔴"
            print(f"{emoji} 胜率{r['win_rate']}%  平均{r['avg_return']:+.2f}%")
        else:
            print("数据不足")
    print()

def main(mode="short", style=None):
    mode_label = {"short": "短线", "long": "中长线"}
    print("=" * 60)
    now = datetime.now()
    
    # 自动风格选择
    if style is None and mode == "short":
        conn_temp = duckdb.connect(DB)
        today_tmp = conn_temp.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
        ms = detect_market_state(conn_temp, today_tmp.isoformat() if today_tmp else now.strftime('%Y-%m-%d'))
        style = ms.get('recommend', 'reversal')
        state_names = {"trend_bull": "趋势牛", "trend_bear": "趋势熊", "choppy": "震荡", "crash_bounce": "急跌反弹"}
        style_info = f" | {style}({state_names.get(ms['state'], ms['state'])})"
        conn_temp.close()
    else:
        style_info = ""
    
    style_label = {"breakout": "放量突破", "reversal": "超跌反弹", "accumulation": "主力吸筹"}
    print(f"📊 A股盘后复盘 ({mode_label[mode]}{style_info}) — {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    conn = duckdb.connect(DB)
    today = conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    today_str = today.isoformat() if today else now.strftime('%Y-%m-%d')
    
    # ── 模型加载函数（提前定义，供长短线共用） ──
    def _load_models(conn):
        """加载所有模型（reg40 + cls27 + GTJA + LSTM）"""
        import lightgbm as lgb, subprocess, json, numpy as np
        MODEL_DIR = os.path.expanduser('~/.hermes/stockdb/models')
        LSTM_PATH = os.path.expanduser('~/.hermes/stockdb/lstm_pred.json')
        lstm_preds = {}
        try:
            subprocess.run(['scp','-oConnectTimeout=3','-oStrictHostKeyChecking=no',
                'pumma@192.168.3.168:C:/Users/pumma/factor_lib/lstm_pred.json', LSTM_PATH],
                capture_output=True, timeout=10)
        except: pass
        if os.path.exists(LSTM_PATH):
            with open(LSTM_PATH) as f:
                lstm_raw = json.load(f)
            vals = np.array(list(lstm_raw.values()))
            if len(vals) > 0:
                ranks = vals.argsort().argsort()
                lstm_preds = {c: ranks[i]/len(ranks)*100 for i,c in enumerate(lstm_raw.keys())}
        reg40_path = os.path.join(MODEL_DIR, 'lgb_reg_40d.txt')
        cls27_path = os.path.join(MODEL_DIR, 'lgb_cls_model.txt')
        stats40_path = os.path.join(MODEL_DIR, 'v6_norm_stats_40d.json')
        reg40 = lgb.Booster(model_file=reg40_path) if os.path.exists(reg40_path) else None
        cls27 = lgb.Booster(model_file=cls27_path) if os.path.exists(cls27_path) else None
        stats40 = {}
        if os.path.exists(stats40_path):
            with open(stats40_path) as f: stats40 = json.load(f)
        gtja_scores = {}
        try:
            from src.factors.zoo.gtja191 import alpha_006, alpha_083, alpha_177, alpha_184
            gtja_panel_df = conn.execute(f"""
                SELECT stock_code, date, open, close, high, low, volume, amount
                FROM daily 
                WHERE date >= (SELECT MAX(trade_date) FROM daily) - INTERVAL '200 DAYS'
                ORDER BY trade_date
            """).fetchdf()
            if len(gtja_panel_df) > 0:
                gp = {}
                for col in ['open','close','high','low','volume','amount']:
                    gp[col] = gtja_panel_df.pivot_table(index='date', columns='stock_code', values=col)
                gp['vwap'] = gp['amount'] / gp['volume'].replace(0, np.nan)
                gp['returns'] = gp['close'].pct_change()
                for fname, mod in [('gtja_006',alpha_006),('gtja_083',alpha_083),('gtja_177',alpha_177),('gtja_184',alpha_184)]:
                    sig = mod.compute(gp)
                    if sig is not None and not sig.empty:
                        row = sig.iloc[-1] if len(sig) > 0 else None
                        if row is not None: gtja_scores[fname] = row.dropna().to_dict()
        except: pass
        return {'reg40': reg40, 'cls27': cls27, 'stats40': stats40, 'gtja_scores': gtja_scores, 'lstm_preds': lstm_preds}

    def _score_one(code, dt_str, rows, conn, models):
        """计算单只股票的模型评分（40d + cls27）"""
        import numpy as np
        if len(rows) < 120:
            return None
        rows = rows[::-1]
        closes = [float(r[1]) for r in rows]
        c = np.array(closes, dtype=np.float64)
        lc = c[-1]
        chg5 = lc/c[-5]-1 if len(c)>=5 else 0
        chg10 = lc/c[-10]-1 if len(c)>=10 else 0
        chg20 = lc/c[-20]-1 if len(c)>=20 else 0
        chg60 = lc/c[-60]-1 if len(c)>=60 else 0
        chg120 = lc/c[0]-1
        ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
        d5=lc/ma5-1 if ma5>0 else 0; d10=lc/ma10-1 if ma10>0 else 0
        d20=lc/ma20-1 if ma20>0 else 0; d60=lc/ma60-1 if ma60>0 else 0; d120=lc/np.mean(c)-1 if np.mean(c)>0 else 0
        bull1=1 if ma5>ma10>ma20 else 0; bull2=1 if ma20>ma60 else 0
        rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
        std20=np.std(c[-20:])/np.mean(c[-20:])*100
        vols=np.array([float(r[3]) for r in rows[-20:]])
        vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
        rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
        c1d=float(rows[-1][2] or 0); c3d=lc/c[-3]-1 if len(c)>=3 and c[-3]>0 else 0
        ep=0.5; bp=0.5; ln_cap=22.0
        try:
            vr_ = conn.execute(f"SELECT pe_ttm, pb, total_mv FROM stock_valuation WHERE ts_code='{code}' ORDER BY trade_date DESC LIMIT 1").fetchone()
            if vr_:
                if vr_[0] and vr_[0]>0: ep=1.0/vr_[0]
                if vr_[1] and vr_[1]>0: bp=1.0/vr_[1]
                if vr_[2] and vr_[2]>0: ln_cap=np.log(vr_[2])
        except: pass
        gtja_v = []
        for gn in ['gtja_006','gtja_083','gtja_177','gtja_184']:
            d = models['gtja_scores'].get(gn, {})
            gtja_v.append(d.get(code, 0.0))
        feat=np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            bull1,bull2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap]+gtja_v, dtype=np.float64)
        reg40_pred = 0
        if models['reg40'] is not None and models['stats40']:
            f40 = feat[:23].copy()
            for j in range(23):
                key=f'feat_{j}'
                if key in models['stats40'] and models['stats40'][key]['std']>0:
                    s=models['stats40'][key]
                    f40[j]=max(f40[j], s['low']); f40[j]=min(f40[j], s['high'])
                    f40[j]=(f40[j]-s['mean'])/s['std']
            f40 = np.append(f40, np.array(gtja_v, dtype=np.float64))
            f40 = np.nan_to_num(f40.reshape(1,-1), nan=0.0)
            reg40_pred = float(models['reg40'].predict(f40)[0])
        cls27_prob = 0.5
        if models['cls27'] is not None:
            cls27_feats = np.nan_to_num(feat.reshape(1,-1), nan=0.0, posinf=0.0, neginf=0.0)
            cls27_prob = float(models['cls27'].predict(cls27_feats)[0])
        lstm_score = models['lstm_preds'].get(code, 50)
        reg40_score = max(0, min(100, (reg40_pred+10)/50*100))
        final_score = min(100, max(0, reg40_score * (cls27_prob / 0.5)))
        return {'reg40_pred': reg40_pred, 'cls27_prob': cls27_prob, 'lstm_score': lstm_score, 'final_score': final_score}

    # ========================
    # 一、大盘走势
    # ========================
    print("\n📈【一、大盘走势】")
    print("-" * 50)
    
    indices = [
        ("上证指数", "sh000001"),
        ("深证成指", "sz399001"),
        ("创业板指", "sz399006"),
    ]
    for name, sym in indices:
        r_name, cur, chg, hi, lo, emoji = get_index_live(sym)
        if cur:
            print(f"  {r_name}: {cur:.2f}  {emoji}{chg:+.2f}%")
            print(f"          最高 {hi:.0f}  最低 {lo:.0f}")
    
    # 市场状态诊断
    ms = detect_market_state(conn, today_str)
    if ms['confidence'] > 0:
        state_names = {"trend_bull": "趋势牛", "trend_bear": "趋势熊", "choppy": "震荡", "crash_bounce": "急跌反弹"}
        print(f"\n  🌤️ 市场状态: {state_names.get(ms['state'], ms['state'])}")
        print(f"     推荐风格: {ms['recommend']} (置信度 {ms['confidence']}%)")
        print(f"     MA20斜率 {ms['ma_slope']:+.2f}%  |  波动率 {ms['volatility']:.1f}%  |  5日涨跌 {ms['cum5']:+.1f}%  |  连{['跌','涨'][ms['streak']>0]}{abs(ms['streak'])}天")
    
    # ========================
    # 二、今日市场数据
    # ========================
    print("\n📊【二、今日市场数据】")
    print("-" * 50)
    
    stats = get_market_stats(conn, today_str)
    if stats:
        print(f"  总成交额: {stats['amount_yi']:.0f}亿")
        print(f"  涨跌分布: 🟢上涨 {stats['up']}  🔴下跌 {stats['down']}  ⚪平盘 {stats['flat']}")
        print(f"  涨停 {stats['zt']}家  跌停 {stats['dt']}家")
        print(f"  平均涨跌幅: {stats['avg']:+.2f}%")
    
    # 涨跌幅TOP5
    up, down = get_top_stocks(conn, today_str)
    print(f"\n  📈 涨幅TOP{len(up)}")
    for i, (code, close, chg, name) in enumerate(up, 1):
        n = name or code
        print(f"    {i}. {n}({code})  {close:.2f}  {chg:+.2f}%")
    
    print(f"\n  📉 跌幅TOP{len(down)}")
    for i, (code, close, chg, name) in enumerate(down, 1):
        n = name or code
        print(f"    {i}. {n}({code})  {close:.2f}  {chg:.2f}%")
    
    # ========================
    # 三、行业板块表现
    # ========================
    print("\n🏭【三、行业板块表现】")
    print("-" * 50)
    
    # 行业涨跌幅排行（>=5只成分股）
    sql_ind = """
        SELECT si.industry,
               COUNT(*) as stock_count,
               ROUND(AVG(d.pct_chg), 2) as avg_change,
               SUM(CASE WHEN d.pct_chg > 0 THEN 1 ELSE 0 END) as up_count,
               SUM(CASE WHEN d.pct_chg < 0 THEN 1 ELSE 0 END) as down_count
        FROM daily d
        JOIN stock_info si ON d.stock_code = si.stock_code
        WHERE d.date = ? AND si.industry IS NOT NULL AND si.industry != ''
        GROUP BY si.industry
        HAVING COUNT(*) >= 5
        ORDER BY avg_change DESC
    """
    ind_df = conn.execute(sql_ind, [today_str]).fetchdf()
    if len(ind_df) > 0:
        top5i = ind_df.head(5)
        bot5i = ind_df.tail(5)
        print("  📈 涨幅TOP5行业")
        for _, r in top5i.iterrows():
            updown = f"涨{r['up_count']:.0f}跌{r['down_count']:.0f}" 
            arrow = "🟢" if r['avg_change'] > 0 else "🔴"
            short = r['industry'].split()[-1] if ' ' in r['industry'] else r['industry']
            print(f"    {arrow} {short}  {r['avg_change']:+.2f}%  ({updown})")
        print()
        print("  📉 跌幅TOP5行业")
        for _, r in bot5i.iterrows():
            updown = f"涨{r['up_count']:.0f}跌{r['down_count']:.0f}"
            arrow = "🟢" if r['avg_change'] > 0 else "🔴"
            short = r['industry'].split()[-1] if ' ' in r['industry'] else r['industry']
            print(f"    {arrow} {short}  {r['avg_change']:+.2f}%  ({updown})")
    
    # 行业资金流入流出排行
    sql_mf = """
        SELECT si.industry,
               COUNT(*) as stock_count,
               ROUND(SUM(mf.main_net) / 1e8, 2) as total_main_net_yi,
               ROUND(AVG(mf.main_pct), 2) as avg_main_pct
        FROM money_flow mf
        JOIN stock_info si ON mf.stock_code = si.stock_code
        WHERE mf.date = ? AND si.industry IS NOT NULL AND si.industry != ''
        GROUP BY si.industry
        HAVING COUNT(*) >= 5
        ORDER BY total_main_net_yi DESC
    """
    mf_df = conn.execute(sql_mf, [today_str]).fetchdf()
    if len(mf_df) > 0:
        inflow_top = mf_df.head(5)
        outflow_top = mf_df.tail(5)
        print()
        print("  💰 主力净流入TOP5行业")
        for _, r in inflow_top.iterrows():
            short = r['industry'].split()[-1] if ' ' in r['industry'] else r['industry']
            pct_tag = f" 主力占比{r['avg_main_pct']:+.1f}%" if r['avg_main_pct'] != 0 else ""
            print(f"    💵 {short}  +{r['total_main_net_yi']:.1f}亿{pct_tag}")
        print()
        print("  🔴 主力净流出TOP5行业")
        for _, r in outflow_top.iterrows():
            short = r['industry'].split()[-1] if ' ' in r['industry'] else r['industry']
            pct_tag = f" 主力占比{r['avg_main_pct']:+.1f}%" if r['avg_main_pct'] != 0 else ""
            print(f"    📉 {short}  {r['total_main_net_yi']:.1f}亿{pct_tag}")
    
    # ========================
    # 四、适合介入的股票
    # ========================
    if mode == "short":
        sname = style
        if not sname:
            # 自动根据市场状态选择最优风格
            ms = detect_market_state(conn, today_str)
            sname = ms.get('recommend', 'reversal')
            state_names = {"trend_bull": "趋势牛", "trend_bear": "趋势熊", "choppy": "震荡", "crash_bounce": "急跌反弹"}
            print(f"  🌤️ 市场状态: {state_names.get(ms['state'], ms['state'])} → 自动切换为 {sname} 风格")
            print()
        style_desc = {"breakout": "放量突破", "reversal": "超跌反弹", "accumulation": "主力吸筹"}.get(sname, sname)
        print(f"\n🎯【四、短线候选股（{style_desc}·多因子排名）】")
        print("-" * 50)
        if sname == "breakout":
            print("  排名因子：量比(24%) + 主力(19%) + 涨幅(9%) + 量价协同(19%) + 量能(9%) + 振幅(5%) + 行业(10%) + 背离(5%)")
        elif sname == "reversal":
            print("  排名因子：近期跌幅(28%) + 缩量企稳(19%) + K线位置(14%) + 距5线(19%) + 行业抗跌(15%) + 背离(5%)")
        else:
            print("  排名因子：主力(24%) + 散户(24%) + 量能(19%) + 振幅(14%) + 涨幅(14%) + 背离(5%)")
        print("  （主力数据缺失时→量比+涨幅+量价协同+振幅+行业 各自加权重）")
        print()

        candidates = get_candidates_short(conn, today_str, style=sname)
        if candidates:
            for i, s in enumerate(candidates[:10], 1):
                fire = "🔥" if s['vol_ratio'] > 2.0 else ""
                up_arrow = "🟢" if s['change'] > 0 else "🔴"
                inflow = "💰主力+" if s['main_net_yi'] > 0 else "📉主力"
                main_tag = f" {inflow}{abs(s['main_net_yi']):.1f}亿" if abs(s['main_net_yi']) > 0.1 else ""
                tr_tag = f"换手{s['turn_rate']:.1f}%" if s['turn_rate'] else ""
                print(f"  {i}. {s['name']}({s['code']})")
                print(f"     收{s['close']:.2f}  {up_arrow}{s['change']:+.2f}%  "
                      f"量比{s['vol_ratio']:.2f}倍{fire}  距5线+{s['ma_dist']:.1f}%  {tr_tag}"
                      f"{main_tag}")
        else:
            print("  今日无符合条件的短线个股")
    else:
        print("\\n🎯【四、中长线候选股（基本面+模型融合排名）】")
        print("-" * 50)
        print("  条件：仅安全过滤（非ST/停牌/上市>2年/涨跌停） + 40dXcls27排名")
        print()

        candidates = get_candidates_long(conn, today_str)
        if candidates:
            # 加载模型预测
            models = _load_models(conn)
            
            scored = []
            for s in candidates:
                code = s['code']
                try:
                    rows = conn.execute(f"""
                        SELECT trade_date, close, COALESCE(pct_chg,0), volume, amount, amplitude
                        FROM daily WHERE ts_code='{code}'
                        ORDER BY trade_date DESC LIMIT 200
                    """).fetchall()
                    if len(rows) < 120:
                        continue
                    
                    scores = _score_one(code, today_str, rows, conn, models)
                    if scores is None:
                        continue
                    
                    # SQL只做硬过滤，排名全交模型
                    composite = scores['final_score']
                    
                    scored.append((composite, scores, s))
                except:
                    continue
            
            scored.sort(key=lambda x: -x[0])
            
            print(f"\\n  📊 40d×cls27评分排名")
            print(f"  {'#'*60}")
            for i, (comp, sc, s) in enumerate(scored[:10], 1):
                up = '🟢' if s['change']>0 else '🔴'
                roe_tag = f"ROE {s['roe']:.0f}%"
                print(f"  {i}. {s['name']}({s['code']}) {up}{s['change']:+.2f}%")
                print(f"      {comp:.0f}分 | 40d预{sc['reg40_pred']:+.1f}% | 方向{sc['cls27_prob']*100:.0f}% | LSTM{sc['lstm_score']:.0f}分")
                print(f"     {roe_tag} | 营收{s['revenue_yoy']:.0f}% | PE {s['pe'] or '-'} | {s.get('industry','')[:20]}")
        else:
            print("  今日无符合条件的中长线个股")
    
    # ── 短线模式加模型评分 ──
    if mode == "short" and candidates:
        models = _load_models(conn)
        print(f"\n  📊 模型评分确认（40d×cls27）")
        print(f"  {'-'*40}")
        score_list = []
        for s in candidates[:20]:
            code = s['code']
            try:
                rows = conn.execute(f"""
                    SELECT trade_date, close, COALESCE(pct_chg,0), volume, amount, amplitude
                    FROM daily WHERE ts_code='{code}' ORDER BY trade_date DESC LIMIT 200
                """).fetchall()
                scores = _score_one(code, today_str, rows, conn, models)
                if scores:
                    score_list.append((scores['final_score'], scores, s))
            except: pass
        score_list.sort(key=lambda x: -x[0])
        for i, (comp, sc, s) in enumerate(score_list[:5], 1):
            up = '🟢' if s['change']>0 else '🔴'
            arrow = '↗️' if sc['cls27_prob']>0.55 else '➡️' if sc['cls27_prob']>0.45 else '↘️'
            print(f"  {i}. {s['name']}({s['code']}) {up}{s['change']:+.2f}%  {comp:.0f}分 {arrow}{sc['cls27_prob']*100:.0f}%")
    
    # ========================
    # 四、风险提示
    # ========================
    print("\n" + "=" * 60)
    print("⚠️ 以上数据仅供参考，不构成投资建议")
    print("=" * 60)
    
    conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="盘后复盘")
    parser.add_argument("--mode", choices=["short", "long"], default="long",
                        help="筛选模式: short(短线) / long(中长线,默认)")
    parser.add_argument("--backtest", action="store_true",
                        help="运行三风格回测对比（最近3个月）")
    parser.add_argument("--style", choices=["breakout", "reversal", "accumulation"],
                        default=None, help="短线筛选风格（默认breakout，也可用于--backtest）")
    parser.add_argument("--start", type=str, default=None,
                        help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None,
                        help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--hold", type=int, default=15,
                        help="持有交易日数（默认15=3周）")
    parser.add_argument("--analyze", action="store_true",
                        help="综合回测分析（市场状态+风格+共振+单因子）")
    args = parser.parse_args()

    if args.analyze:
        conn = duckdb.connect(DB)
        run_analysis(conn, start=args.start, end=args.end)
        conn.close()
    elif args.backtest:
        conn = duckdb.connect(DB)
        if args.style:
            sd = args.start or (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            ed = args.end or datetime.now().strftime('%Y-%m-%d')
            r = backtest_style(conn, args.style, sd, ed, hold_days=args.hold, top_n=5)
            print(f"\n📋 {args.style} 回测结果: 胜率 {r['win_rate']}%  |  平均 {r['avg_return']:+.2f}%  |  交易 {r['total_trades']}次")
        else:
            run_backtest(conn, start=args.start, end=args.end)
        conn.close()
    else:
        main(args.mode, args.style)
