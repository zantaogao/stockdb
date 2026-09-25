#!/usr/bin/env python3
"""
五维评分系统 v2 — Barra式连续评分，Agent无权推翻

用法: python3 scoring.py <6位股票代码> [--mode short|long]
  short (默认): 短线，重技术+资金+动量+量能
  long:         中长线，重业绩+估值+品质+负债

核心改进：
  - 连续打分代替硬阈值（ROE>20→满分 → ROE每高5%累进）
  - 短线新增 动量面（15分）
  - 长线新增 负债面（10分）
  - 估值面加入行业相对比较
"""

import duckdb, json, sys, argparse
from pathlib import Path
from datetime import datetime, date, timedelta

DB_DIR = Path.home() / '.hermes' / 'stockdb'
TODAY = date.today()

# ─── 两套权重 ───
WEIGHTS = {
    "short": {"业绩面": 10, "技术面": 30, "动量面": 15, "资金面": 25, "估值面": 5, "量能面": 15},
    "long":  {"业绩面": 30, "技术面": 25, "动量面": 0,  "资金面": 10, "估值面": 15, "量能面": 5, "负债面": 10, "品质面": 5},
}
RAW_MAX = {"业绩面": 30, "技术面": 25, "动量面": 15, "资金面": 25, "估值面": 10, "量能面": 10, "负债面": 10, "品质面": 10}


def connect():
    return duckdb.connect(str(DB_DIR / 'tushare.db'), read_only=True)


def get_latest_trading_day(db, code):
    r = db.execute(f"SELECT MAX(trade_date) FROM daily WHERE ts_code LIKE '{code}%'").fetchone()
    return r[0] if r[0] else None


def _linear_score(value, breakpoints):
    """连续打分：breakpoints = [(threshold, score), ...]，超过阈值即得对应分，线性插值"""
    if value is None:
        return 0
    prev_t, prev_s = 0, 0
    for t, s in sorted(breakpoints):
        if value >= t:
            prev_t, prev_s = t, s
        else:
            # 线性插值
            if prev_t == t:
                return s if value >= t else 0
            ratio = (value - prev_t) / (t - prev_t)
            return round(prev_s + (s - prev_s) * ratio, 1)
    return prev_s


# ═══════════════════════════════════════════
# 业绩面 0~30分
# ═══════════════════════════════════════════
def score_performance(db, code, mode="short"):
    r = db.execute(f"""
        SELECT revenue_yoy, profit_yoy, gross_margin, net_margin, roe
        FROM fin_income
        WHERE ts_code LIKE '{code}%'
        ORDER BY end_date DESC LIMIT 1
    """).fetchone()
    r2 = db.execute(f"""
        SELECT roe FROM fin_income
        WHERE ts_code LIKE '{code}%' AND SUBSTR(end_date,5,2)='12'
        ORDER BY end_date DESC LIMIT 1
    """).fetchone()

    if not r:
        return 0, {}

    rev_yoy, profit_yoy = float(r[0]) if r[0] else 0, float(r[1]) if r[1] else 0
    gross, net_m = float(r[2]) if r[2] else 0, float(r[3]) if r[3] else 0
    annual_roe = float(r2[0]) if r2 and r2[0] else None
    roe_val = float(r[4]) if r[4] else 0
    roe = annual_roe if annual_roe is not None else roe_val

    # 连续打分：每5%营收增速=1.5分，利润每5%=1.5分，ROE每2%=1分
    rev_s = min(10, round(rev_yoy / 5 * 1.5, 1)) if rev_yoy > 0 else 0
    profit_s = min(10, round(profit_yoy / 5 * 1.5, 1)) if profit_yoy > 0 else 0
    roe_s = min(10, round(roe / 2 * 1, 1)) if roe > 0 else 0

    s = round(rev_s + profit_s + roe_s, 1)
    return s, {"营收增速": round(rev_yoy, 1), "利润增速": round(profit_yoy, 1),
                "毛利率": f"{round(gross,1)}%", "ROE": round(roe, 1)}


# ═══════════════════════════════════════════
# 技术面 0~25分
# ═══════════════════════════════════════════
def score_technical(db, code, latest_date, mode="short"):
    rows = db.execute(f"""
        SELECT close, vol, pct_chg FROM daily
        WHERE ts_code LIKE '{code}%' AND trade_date <= '{latest_date}'
        ORDER BY trade_date DESC LIMIT 200
    """).fetchall()
    if len(rows) < 60:
        return 0, {"均线": "数据不足"}

    c = [float(r[0]) for r in rows]
    p = c[0]

    # ── 硬过滤 ──
    today = rows[0]
    turn = float(today[1]) if today[1] else 0
    chg = float(today[2]) if today[2] else 0
    # 换手率过高或过低 → 扣分
    hard_penalty = 0
    if turn > 15: hard_penalty -= 3
    elif turn < 0.3: hard_penalty -= 2
    # 涨跌幅异常 → 扣分
    if abs(chg) > 9: hard_penalty -= 5  # 接近涨跌停
    elif chg > 7: hard_penalty -= 2     # 大涨
    elif chg < -7: hard_penalty -= 3    # 大跌

    def ma(n): return sum(c[:n]) / n if len(c) >= n else None
    ma5, ma10, ma20, ma60, ma200 = ma(5), ma(10), ma(20), ma(60), ma(200)

    s, det = 0, {}
    n = mode

    # 均线排列 (10分) — 连续：MA5>MA10得3，每多一层+3
    score_ma = 0
    if ma5 and ma10:
        if n == "short":
            if ma5 > ma10 and p > ma5: score_ma += 4
            if ma10 > ma20: score_ma += 3
            if ma20 > ma60: score_ma += 3
        else:
            if ma5 > ma10 > ma20: score_ma += 6
            if ma20 > ma60: score_ma += 4
    s += min(10, score_ma)
    det["均线得分"] = score_ma

    # 60日涨幅 (7分) — 短线不惩罚高涨幅（反转股已反弹很正常）
    if len(c) >= 60:
        ret = (p - c[59]) / c[59] * 100
        det["60日涨幅"] = f"{round(ret,1)}%"
        if n == "short":
            # 反转策略：不惩罚已反弹的，越低越好但高也不扣分
            if ret > 0:
                score_ret = 7 - abs(ret - 15) / 15 if ret < 50 else max(3, 7 - abs(ret - 15) / 30)
            else:
                score_ret = max(0, 3 + ret / 10)
        else:
            score_ret = 5 - abs(ret - 25) / 15 if 5 < ret < 60 else max(0, 2 - abs(ret - 25) / 30)
        s += max(0, round(score_ret, 1))

    # 年线位置 (8分) — 站上+偏离合理
    if ma200 and ma200 > 0:
        dist = (p - ma200) / ma200 * 100
        det["距年线"] = f"{round(dist,1)}%"
        if n == "short":
            score_ma200 = 8 - abs(dist - 15) / 10 if 0 < dist < 50 else max(1, 4 - abs(dist - 15) / 20)
        else:
            score_ma200 = 8 - abs(dist - 20) / 10 if 5 < dist < 50 else max(1, 3)
        s += max(0, round(score_ma200, 1))
    else:
        det["距年线"] = "数据不足"
        s += 3

    # 应用硬过滤扣分
    s += hard_penalty
    return min(25, max(0, round(s))), det


# ═══════════════════════════════════════════
# 动量面 0~15分（短线专用）
# ═══════════════════════════════════════════
def score_momentum(db, code, latest_date, mode="short"):
    if mode != "short":
        return 0, {}
    rows = db.execute(f"""
        SELECT close, pct_chg FROM daily
        WHERE ts_code LIKE '{code}%' AND trade_date <= '{latest_date}'
        ORDER BY trade_date DESC LIMIT 5
    """).fetchall()
    if len(rows) < 3:
        return 0, {"动量": "数据不足"}

    # 近3日涨幅强度 (7分)
    chgs = [float(r[1]) for r in rows[:3] if r[1] is not None]
    avg_chg = sum(chgs) / len(chgs) if chgs else 0
    m_s = _linear_score(avg_chg, [(1, 2), (2, 4), (4, 7)])

    # 近3日是否持续收阳 (8分)
    n_up = sum(1 for r in rows[:3] if r[1] is not None and float(r[1]) > 0)
    s_s = n_up / 3 * 8 if len(rows[:3]) >= 2 else 0

    s = round(m_s + s_s, 1)
    return max(0, min(15, s)), {"近3日涨幅均值": f"{round(avg_chg,2)}%", "连阳天数": f"{n_up}/3"}


# ═══════════════════════════════════════════
# 资金面 0~25分
# ═══════════════════════════════════════════
def score_money_flow(db, code, latest_date, mode="short"):
    window = 5 if mode == "short" else 30
    label = f"{window}日"
    r = db.execute(f"""
        SELECT COALESCE(SUM(main_net),0), COALESCE(SUM(retail_net),0),
               COUNT(*) as records
        FROM money_flow
        WHERE stock_code='{code}' AND date >= CAST(SUBSTR('{latest_date}',1,4) || '-' || SUBSTR('{latest_date}',5,2) || '-' || SUBSTR('{latest_date}',7,2) AS DATE) - INTERVAL '{window}' DAY
    """).fetchone()
    if not r or r[2] == 0:
        # 无主力数据 → 跳过该维度，不扣分
        return None, {"主力流入": "无数据(跳过)"}

    main_net, retail_net = float(r[0] or 0), float(r[1] or 0)
    main_yi = main_net / 1e8
    retail_yi = retail_net / 1e8

    amount_r = db.execute(f"""
        SELECT SUM(amount) FROM (
            SELECT amount FROM daily
            WHERE ts_code LIKE '{code}%' AND trade_date <= '{latest_date}'
            ORDER BY trade_date DESC LIMIT {window}
        )
    """).fetchall()
    total = sum(float(row[0]) for row in amount_r) if amount_r else 1
    main_pct = main_net / total * 100 if total > 0 else 0

    # 连续打分 — 改进版：更细的阶梯，避免过早饱和
    # 主力净流入(亿): 0→0, 0.2→2, 0.5→4, 1→6, 2→8, 5→10, 10→12
    if main_yi > 0:
        if main_yi < 0.2: s_main = main_yi / 0.2 * 2
        elif main_yi < 0.5: s_main = 2 + (main_yi - 0.2) / 0.3 * 2
        elif main_yi < 1: s_main = 4 + (main_yi - 0.5) / 0.5 * 2
        elif main_yi < 2: s_main = 6 + (main_yi - 1) / 1 * 2
        elif main_yi < 5: s_main = 8 + (main_yi - 2) / 3 * 2
        elif main_yi < 10: s_main = 10 + (main_yi - 5) / 5 * 2
        else: s_main = 12  # 10亿+封顶
    else:
        s_main = max(-3, main_yi / 0.5 * 2)  # 净流出扣分
    s_main = max(-3, min(12, s_main))
    
    s_pct = _linear_score(main_pct, [(0, 0), (1, 2), (3, 4), (6, 6), (10, 8)])
    s_pct = min(8, s_pct)
    s_retail = 7 if retail_yi < -0.1 else (3 if retail_yi < 0 else 0)
    s = round(s_main + s_pct + s_retail, 1)

    return min(25, s), {
        f"主力{label}净流入": f"{round(main_yi,2)}亿",
        "主力净占比": f"{round(main_pct,2)}%",
        f"散户{label}净流向": f"{'流出' if retail_yi<0 else '流入'} {abs(round(retail_yi,2))}亿"
    }


# ═══════════════════════════════════════════
# 估值面 0~10分 — 加入行业相对比较
# ═══════════════════════════════════════════
def score_valuation(db, code, latest_date, mode="short"):
    # daily_basic uses stock_code without suffix, date as DATE type
    r = db.execute(f"""
        SELECT pe_ttm, pb FROM daily_basic
        WHERE ts_code LIKE '{code}%' ORDER BY trade_date DESC LIMIT 1
    """).fetchone()

    pe_ttm, pb = None, None
    if r and r[0] is not None:
        pe_ttm = float(r[0])
        pb = float(r[1]) if r[1] else None
    else:
        try:
            import urllib.request
            market = "sz" if code.startswith("00") or code.startswith("30") else "sh"
            resp = urllib.request.urlopen(f"https://qt.gtimg.cn/q={market}{code}", timeout=5).read()
            text = resp.decode("gbk", errors="replace")
            parts = text.split("~")
            if len(parts) >= 40:
                pe_str = parts[39].strip()
                pe_ttm = float(pe_str) if pe_str and pe_str.replace('.','',1).replace('-','',1).isdigit() else None
        except: pass

    # 获取行业平均PE
    ind = db.execute(f"SELECT industry FROM stock_info WHERE stock_code='{code}'").fetchone()
    industry_pe = None
    if ind and ind[0]:
        ind_pe = db.execute(f"""
            SELECT AVG(v.pe_ttm) FROM daily_basic v
            JOIN stock_info s ON SUBSTR(v.ts_code, 1, 6) = s.stock_code
            WHERE s.industry = '{ind[0]}' AND v.pe_ttm > 0 AND v.pe_ttm < 200
        """).fetchone()
        industry_pe = float(ind_pe[0]) if ind_pe and ind_pe[0] else None

    fin = db.execute(f"SELECT profit_yoy FROM fin_income WHERE ts_code LIKE '{code}%' ORDER BY end_date DESC LIMIT 1").fetchone()
    profit_yoy = float(fin[0]) if fin and fin[0] else None

    s, det = 0, {"PE(TTM)": pe_ttm, "PB": pb}
    if industry_pe:
        det["行业平均PE"] = round(industry_pe, 2)

    if pe_ttm and pe_ttm > 0:
        if profit_yoy and profit_yoy > 0:
            peg = pe_ttm / profit_yoy
            det["PEG"] = round(peg, 2)
            # PEG连续打分 — 区分高成长行业和传统行业
            # 修复：PEG>5的不深度惩罚（可能只是利润增速低，不是估值高）
            is_high_growth = bool(ind and ind[0] and any(kw in ind[0] for kw in ["计算机","通信","电子","半导体","软件","医药","医疗","新能源","光伏","锂电","AI","机器人"]))
            if is_high_growth:
                s = _linear_score(peg, [(0, 10), (1, 9), (1.5, 7), (2.5, 5), (4, 3), (6, 1)])
            else:
                s = _linear_score(peg, [(0, 10), (0.8, 8), (1.5, 5), (2.5, 3), (4, 1), (8, 0)])
                # 传统行业PEG容忍度：1以下满分，超过8才归零
        else:
            # PE相对行业
            if industry_pe and industry_pe > 0:
                pe_ratio = pe_ttm / industry_pe
                s = _linear_score(pe_ratio, [(0, 10), (0.5, 8), (0.8, 6), (1.2, 4), (2, 2)])
            else:
                s = _linear_score(pe_ttm, [(0, 0), (10, 5), (20, 7), (30, 5), (50, 2), (100, 0)])
        det["估值评分"] = round(s, 1)
    else:
        det["说明"] = "PE为负(亏损)"

    return min(10, round(s)), det


# ═══════════════════════════════════════════
# 量能面 0~10分
# ═══════════════════════════════════════════
def score_volume(db, code, latest_date, mode="short"):
    amounts = db.execute(f"""
        SELECT amount, vol FROM daily
        WHERE ts_code LIKE '{code}%' AND trade_date <= '{latest_date}'
        ORDER BY trade_date DESC LIMIT 60
    """).fetchall()
    if not amounts or len(amounts) < 2:
        return 0, {"量比": None}

    cur_amt = float(amounts[0][0]) if amounts[0][0] else 0
    # 成交额绝对值门槛（防小票失真）—— <8 亿打半折
    if cur_amt < 8e8: s_amt = 0.5
    else: s_amt = 1.0
    avg_amt = sum(float(a[0]) for a in amounts if a[0]) * s_amt / max(1, len([a for a in amounts if a[0]]))
    vol_ratio = cur_amt / avg_amt if avg_amt > 0 else 0
    turn = float(amounts[0][1]) if amounts[0][1] else 0

    det = {"量比": round(vol_ratio, 2), "换手率": f"{round(turn,2)}%"}

    # 连续打分 — 改进版：区分度更高，惩罚巨量
    if mode == "short":
        # 短线：1.2~2.5倍最佳，过高扣分
        if vol_ratio < 0.5: s = 0
        elif vol_ratio < 0.8: s = 1
        elif vol_ratio < 1.2: s = 4
        elif vol_ratio < 1.8: s = 7
        elif vol_ratio < 2.5: s = 10
        elif vol_ratio < 4: s = 7       # 偏高但还算活跃
        elif vol_ratio < 7: s = 4       # 异常放量，警惕出货
        else: s = 1                      # 巨量，强烈警惕
    else:
        # 长线：0.8~2倍最佳
        if vol_ratio < 0.5: s = 1
        elif vol_ratio < 0.8: s = 4
        elif vol_ratio < 1.2: s = 7
        elif vol_ratio < 2: s = 10
        elif vol_ratio < 3: s = 7
        elif vol_ratio < 5: s = 4
        else: s = 1

    return min(10, round(s)), det


# ═══════════════════════════════════════════
# 负债面 0~10分（长线专用）
# ═══════════════════════════════════════════
def score_debt(db, code, latest_date, mode="short"):
    if mode != "long":
        return 0, {}
    r = db.execute(f"""
        SELECT debt_ratio FROM fin_balance
        WHERE ts_code LIKE '{code}%'
        ORDER BY end_date DESC LIMIT 1
    """).fetchone()
    if not r or r[0] is None:
        return 0, {}
    debt = float(r[0])
    s = _linear_score(debt, [(0, 10), (30, 8), (50, 5), (70, 2), (90, 0)])
    return min(10, round(s)), {"负债率": f"{round(debt,1)}%"}


# ═══════════════════════════════════════════
# 品质面 0~10分（长线专用：盈利稳定性+现金流）
# ═══════════════════════════════════════════
def score_quality(db, code, latest_date, mode="short"):
    if mode != "long":
        return 0, {}
    # 盈利稳定性：近3年利润增速 >0
    profits = db.execute(f"""
        SELECT profit_yoy FROM fin_income
        WHERE ts_code LIKE '{code}%' AND SUBSTR(end_date,5,2)='12'
        ORDER BY end_date DESC LIMIT 3
    """).fetchall()
    n_pos = sum(1 for r in profits if r[0] and float(r[0]) > 0)
    n_total = len(profits)
    s1 = round(n_pos / max(3, n_total) * 5, 1) if n_total > 0 else 0

    # 自由现金流
    cf = db.execute(f"""
        SELECT free_cf FROM fin_cashflow
        WHERE ts_code LIKE '{code}%' ORDER BY end_date DESC LIMIT 1
    """).fetchone()
    cf_val = float(cf[0]) if cf and cf[0] else None
    s2 = _linear_score(cf_val / 1e8 if cf_val else 0, [(0, 0), (1, 2), (5, 4), (10, 5)]) if cf_val is not None else 0

    s = round(s1 + s2, 1)
    det = {}
    det[f"近3年盈利年数"] = f"{n_pos}/{n_total}"
    if cf_val is not None: det["自由现金流"] = f"{round(cf_val/1e8,2)}亿"
    return min(10, s), det


# ═══════════════════════════════════════════
# 风险揭示（不变）
# ═══════════════════════════════════════════
def get_risk_details(db, code, latest_date):
    risks = {}
    # 60日涨幅
    rows = db.execute(f"SELECT close FROM daily WHERE ts_code LIKE '{code}%' AND trade_date<='{latest_date}' ORDER BY trade_date DESC LIMIT 60").fetchall()
    if len(rows) >= 60:
        ret = (rows[0][0] - rows[59][0]) / rows[59][0] * 100
        risks["60日涨幅"] = f"{round(ret,1)}%"
        if ret > 30: risks["⚠️ 超买"] = f"60日涨幅{round(ret,1)}%"

    # 距年线
    rows200 = db.execute(f"SELECT close FROM daily WHERE ts_code LIKE '{code}%' AND trade_date<='{latest_date}' ORDER BY trade_date DESC LIMIT 200").fetchall()
    if len(rows200) >= 200:
        ma200 = sum(float(r[0]) for r in rows200) / 200
        dist = (rows200[0][0] - ma200) / ma200 * 100
        risks["距年线"] = f"{round(dist,1)}%"
        if dist > 30: risks["⚠️ 偏离年线"] = f"{round(dist,1)}%"

    # PEG
    pe_r = db.execute(f"SELECT pe_ttm FROM daily_basic WHERE ts_code LIKE '{code}%' ORDER BY trade_date DESC LIMIT 1").fetchone()
    pe = float(pe_r[0]) if pe_r and pe_r[0] else None
    if not pe:
        try:
            import urllib.request
            market = "sz" if code.startswith("00") or code.startswith("30") else "sh"
            resp = urllib.request.urlopen(f"https://qt.gtimg.cn/q={market}{code}", timeout=5).read()
            parts = resp.decode("gbk", errors="replace").split("~")
            pe = float(parts[39]) if len(parts) > 39 and parts[39].strip().replace('.','',1).replace('-','',1).isdigit() else None
        except: pass
    if pe:
        fin = db.execute(f"SELECT profit_yoy FROM fin_income WHERE ts_code LIKE '{code}%' ORDER BY end_date DESC LIMIT 1").fetchone()
        if fin and fin[0] and float(fin[0]) > 0:
            peg = pe / float(fin[0])
            risks["PEG"] = round(peg, 2)
            if peg > 1.5: risks["⚠️ 估值偏高"] = f"PEG {round(peg,2)}"

    # 近5日回撤
    rows5 = db.execute(f"SELECT high,low FROM daily WHERE ts_code LIKE '{code}%' AND trade_date<='{latest_date}' ORDER BY trade_date DESC LIMIT 5").fetchall()
    if len(rows5) >= 2:
        max_h = max(float(r[0]) for r in rows5)
        min_l = min(float(r[1]) for r in rows5)
        risks["近5日最大回撤"] = f"{round((max_h-min_l)/max_h*100, 1)}%"
    return risks


def main(code, mode="short"):
    db = connect()
    info = db.execute(f"SELECT stock_name, industry, market FROM stock_info WHERE stock_code='{code}'").fetchone()
    if not info:
        print(f"未找到股票 {code}"); db.close(); return
    name, industry, board = info
    latest_date = get_latest_trading_day(db, code)
    if not latest_date:
        print(f"股票 {code} 无日线数据"); db.close(); return

    w = WEIGHTS[mode]

    # 各维度评分（返回 raw 分）
    raw_scores = [
        ("业绩面", score_performance(db, code, mode), 30),
        ("技术面", score_technical(db, code, latest_date, mode), 25),
    ]
    if mode == "short":
        raw_scores.append(("动量面", score_momentum(db, code, latest_date, mode), 15))
    raw_scores += [
        ("资金面", score_money_flow(db, code, latest_date, mode), 25),
        ("估值面", score_valuation(db, code, latest_date, mode), 10),
        ("量能面", score_volume(db, code, latest_date, mode), 10),
    ]
    if mode == "long":
        raw_scores += [
            ("负债面", score_debt(db, code, latest_date, mode), 10),
            ("品质面", score_quality(db, code, latest_date, mode), 10),
        ]

    weighted_scores = {}
    total = 0
    total_weight = sum(w.values())
    used_weight = 0
    for name_s, result, max_s in raw_scores:
        raw_s, detail_s = result if isinstance(result, tuple) else (result, {})
        if raw_s is None:
            # 维度无数据 → 跳过，权重重新分配
            pass
        else:
            weight = w.get(name_s, 0)
            if weight > 0:
                # 归一化到 0~100
                normed = raw_s / max_s * 100
                weighted_scores[name_s] = {"raw": round(raw_s, 1), "weight": weight, "normalized": round(normed, 1)}
                total += normed * weight
                used_weight += weight

    if used_weight > 0:
        final_score = round(total / used_weight, 1)
    else:
        final_score = 0

    risks = get_risk_details(db, code, latest_date)
    result = {
        "code": code, "name": name, "industry": industry, "board": board,
        "latest_date": latest_date, "mode": mode,
        "score": final_score,
        "weighted_scores": weighted_scores,
        "risks": risks
    }

    db.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("code", help="6位股票代码")
    parser.add_argument("--mode", choices=["short", "long"], default="short", help="短线/长线模式")
    args = parser.parse_args()
    result = main(args.code, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
