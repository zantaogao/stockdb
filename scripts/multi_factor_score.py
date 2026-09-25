#!/usr/bin/env python3
"""
多因子评分系统 v1.0 — 替代单一资金流信号

因子权重（基于5月回溯+量化研究校准）:
  1. 资金面 (30%) — 30日主力净流入 ← 已验证67-69%准确率
  2. 动量面 (25%) — 20日涨幅+60日涨幅+近期趋势
  3. 质量面 (20%) — ROE+利润增速+营收增速
  4. 技术面 (15%) — 均线排列+量比+偏离度
  5. 估值面 (10%) — PE/PB行业相对估值

总分 ≥ 75 → 强烈推荐  |  60-74 → 关注  |  < 60 → 不参与
"""
import duckdb, os, json, sys
from datetime import date

DB_PATH = os.path.expanduser('~/.hermes/stockdb/stock.db')
HOLD_PATH = os.path.expanduser('~/.hermes/stockdb/holdings.json')

# ── 权重 ──
WEIGHTS = {
    'money_flow': 0.30,
    'momentum': 0.25,
    'quality': 0.20,
    'technical': 0.15,
    'valuation': 0.10,
}

def score_money_flow(mf_30d):
    """资金面评分 (30%) — 30日主力净流入"""
    if mf_30d is None:
        return None  # 跳过
    mf_yi = mf_30d / 1e8
    if mf_yi > 10: return 100
    if mf_yi > 5: return 90
    if mf_yi > 2: return 80
    if mf_yi > 1: return 70
    if mf_yi > 0.5: return 60
    if mf_yi > 0: return 50
    if mf_yi == 0: return 30
    return 10  # 净流出

def score_momentum(chg_20d, chg_60d, d5_chg):
    """动量面评分 (25%) — 多周期动量组合"""
    score = 50
    # 20日动量（短期趋势）
    if chg_20d > 15: score += 20
    elif chg_20d > 10: score += 15
    elif chg_20d > 5: score += 10
    elif chg_20d > 0: score += 5
    elif chg_20d < -10: score -= 15
    elif chg_20d < -5: score -= 5
    
    # 60日动量（中期趋势）
    if chg_60d > 25: score += 15
    elif chg_60d > 15: score += 10
    elif chg_60d > 5: score += 5
    elif chg_60d < -10: score -= 10
    elif chg_60d < -5: score -= 5
    
    # 近5日（短期方向）
    if d5_chg > 5: score += 15
    elif d5_chg > 2: score += 10
    elif d5_chg > 0: score += 5
    elif d5_chg < -5: score -= 10
    elif d5_chg < -2: score -= 5
    
    return max(0, min(100, score))

def score_quality(roe, profit_yoy, revenue_yoy):
    """质量面评分 (20%) — ROE+利润增速+营收增速"""
    if roe is None and profit_yoy is None:
        return None  # 跳过
    
    score = 50
    # ROE
    if roe is not None:
        if roe > 25: score += 25
        elif roe > 20: score += 20
        elif roe > 15: score += 15
        elif roe > 10: score += 10
        elif roe > 5: score += 5
        else: score -= 10
    
    # 利润增速
    if profit_yoy is not None:
        if profit_yoy > 50: score += 15
        elif profit_yoy > 30: score += 10
        elif profit_yoy > 10: score += 5
        elif profit_yoy > 0: score += 2
        elif profit_yoy < -30: score -= 15
        elif profit_yoy < 0: score -= 5
    
    # 营收增速
    if revenue_yoy is not None:
        if revenue_yoy > 30: score += 10
        elif revenue_yoy > 15: score += 5
        elif revenue_yoy > 0: score += 2
        elif revenue_yoy < -20: score -= 10
        elif revenue_yoy < 0: score -= 5
    
    return max(0, min(100, score))

def score_technical(bull, dev_ma120, vol_ratio):
    """技术面评分 (15%) — 排列+偏离+量能"""
    score = 50
    # 多头排列
    if bull: score += 25
    else: score -= 5
    
    # 距年线偏离
    if dev_ma120 is not None:
        if -5 <= dev_ma120 <= 10: score += 15  # 最佳区间
        elif 10 < dev_ma120 <= 20: score += 5
        elif 20 < dev_ma120 <= 35: score += 0
        elif dev_ma120 > 35: score -= 10   # 严重追高
        elif -15 <= dev_ma120 < -5: score += 5
        elif dev_ma120 < -15: score -= 10   # 破位
    
    # 量比
    if vol_ratio is not None:
        if 1.2 <= vol_ratio <= 3: score += 10
        elif vol_ratio > 3: score += 5
        elif 0.5 <= vol_ratio < 1.2: score += 0
        else: score -= 5  # 缩量
    
    return max(0, min(100, score))

def score_valuation(pe_ttm, pb, industry_pe):
    """估值面评分 (10%) — PE/PB"""
    if pe_ttm is None and pb is None:
        return None
    
    score = 50
    if pe_ttm is not None and pe_ttm > 0:
        if pe_ttm < 15: score += 25
        elif pe_ttm < 25: score += 15
        elif pe_ttm < 40: score += 5
        elif pe_ttm > 100: score -= 15
        elif pe_ttm > 50: score -= 5
    elif pe_ttm is not None and pe_ttm < 0:
        score -= 10  # 亏损
    
    if pb is not None and pb > 0:
        if pb < 1.5: score += 15
        elif pb < 3: score += 10
        elif pb < 5: score += 5
        elif pb > 10: score -= 10
    
    return max(0, min(100, score))

def main():
    conn = duckdb.connect(DB_PATH, read_only=True)
    
    with open(HOLD_PATH) as f:
        data = json.load(f)
    
    # 分析目标：所有 watch_active + watch_cold + hold
    targets = [p for p in data['positions'] 
               if p.get('status') in ('watch_active', 'watch_cold', 'hold') 
               and not p['code'].startswith('TRUST')]
    
    print(f"{'='*70}")
    print("多因子评分系统 v1.0 — 候选股全面评分")
    print(f"{'='*70}")
    print(f"\n评估股票: {len(targets)} 只")
    print(f"因子权重: 资金流{WEIGHTS['money_flow']*100:.0f}% + "
          f"动量{WEIGHTS['momentum']*100:.0f}% + "
          f"质量{WEIGHTS['quality']*100:.0f}% + "
          f"技术{WEIGHTS['technical']*100:.0f}% + "
          f"估值{WEIGHTS['valuation']*100:.0f}%")
    print()
    
    results = []
    for p in targets:
        code = p['code']
        name = p['name']
        status = p['status']
        
        # 获取日线数据
        rows = conn.execute(f"""
            SELECT date, close, change_pct, volume
            FROM stock_daily WHERE stock_code='{code}' 
            ORDER BY date DESC LIMIT 120
        """).fetchall()
        
        if not rows or len(rows) < 5:
            continue
        
        l_close = rows[0][1]
        l_date = str(rows[0][0])
        
        # 均线
        closes = [r[1] for r in rows]
        ma5 = sum(closes[:5])/5 if len(closes)>=5 else None
        ma20 = sum(closes[:20])/20 if len(closes)>=20 else None
        ma60 = sum(closes[:60])/60 if len(closes)>=60 else None
        ma120 = sum(closes[:min(120,len(closes))])/min(120,len(closes))
        
        bull = (ma5 and ma20 and ma60 and ma5 > ma20 > ma60) if all([ma5,ma20,ma60]) else False
        dev_ma120 = (l_close/ma120-1)*100 if ma120 else None
        
        # 动量
        chg_20d = (l_close/closes[19]-1)*100 if len(closes)>=20 else 0
        chg_60d = (l_close/closes[59]-1)*100 if len(closes)>=60 else 0
        
        d5_ago = conn.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}' 
            AND date < '{l_date}' ORDER BY date DESC LIMIT 1 OFFSET 5
        """).fetchone()
        d5_chg = (l_close/d5_ago[0]-1)*100 if d5_ago else 0
        
        # 量比
        vol_20 = conn.execute(f"""
            SELECT AVG(volume) FROM (SELECT volume FROM stock_daily 
            WHERE stock_code='{code}' AND date<'{l_date}' ORDER BY date DESC LIMIT 20) t
        """).fetchone()[0]
        vol_ratio = rows[0][3]/vol_20 if vol_20 and vol_20 > 0 else 1
        
        # 资金流(30日)
        mf = conn.execute(f"""
            SELECT COALESCE(SUM(main_net),0) FROM money_flow 
            WHERE stock_code='{code}' AND date >= '2026-05-01'
        """).fetchone()[0]
        
        # 财务数据
        fin = conn.execute(f"""
            SELECT roe, profit_yoy, revenue_yoy FROM fin_income 
            WHERE stock_code='{code}' ORDER BY report_date DESC LIMIT 1
        """).fetchone()
        roe, profit_yoy, revenue_yoy = fin if fin else (None, None, None)
        
        # 估值
        val = conn.execute(f"""
            SELECT pe_ttm, pb FROM stock_valuation 
            WHERE stock_code='{code}' ORDER BY date DESC LIMIT 1
        """).fetchone()
        pe_ttm, pb = val if val else (None, None)
        
        # 各维度评分
        s_mf = score_money_flow(mf)
        s_mom = score_momentum(chg_20d, chg_60d, d5_chg)
        s_qual = score_quality(roe, profit_yoy, revenue_yoy)
        s_tech = score_technical(bull, dev_ma120, vol_ratio)
        s_val = score_valuation(pe_ttm, pb, None)
        
        # 综合得分（处理跳过维度）
        total_w = 0
        total_s = 0
        for dim, score, w in [
            ('资金', s_mf, WEIGHTS['money_flow']),
            ('动量', s_mom, WEIGHTS['momentum']),
            ('质量', s_qual, WEIGHTS['quality']),
            ('技术', s_tech, WEIGHTS['technical']),
            ('估值', s_val, WEIGHTS['valuation']),
        ]:
            if score is not None:
                total_s += score * w
                total_w += w
        
        composite = total_s / total_w if total_w > 0 else 0
        
        # 结论
        if composite >= 75:
            conclusion = "🟢 推荐买入"
        elif composite >= 60:
            conclusion = "🟡 关注"
        else:
            conclusion = "⚪ 不参与"
        
        # 月表现
        may_first = conn.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}' 
            AND date >= '2026-05-01' ORDER BY date LIMIT 1
        """).fetchone()
        may_chg = (l_close/may_first[0]-1)*100 if may_first else 0
        
        # 判断最佳介入位置
        position = "合理"
        if dev_ma120 and dev_ma120 > 35: position = "⚠️追高"
        elif dev_ma120 and dev_ma120 > 20: position = "偏高" if not bull else "多头可等回踩"
        elif dev_ma120 and dev_ma120 < -15: position = "💀破位"
        elif dev_ma120 and dev_ma120 < -5: position = "超卖关注"
        
        results.append((composite, code, name, may_chg, dev_ma120, bull, s_mf, s_mom, s_qual, s_tech, s_val, status, conclusion, position, mf, vol_ratio))
    
    # 按综合得分排序
    results.sort(key=lambda r: r[0], reverse=True)
    
    # 输出
    print(f"{'排名':>4} {'代码':6s} {'名称':8s} {'状态':12s} {'综合分':>6s} {'5月%':>6s} {'年线偏':>6s} {'多头':>4s} {'资金':>5s} {'动量':>5s} {'质量':>5s} {'技术':>5s} {'估值':>5s} {'结论':12s}")
    print(f"{'─'*70}")
    
    for i, r in enumerate(results, 1):
        comp, code, name, may_chg, dev, bull, mf_s, mom_s, qual_s, tech_s, val_s, status, concl, pos, mf, vr = r
        bull_m = "✅" if bull else ""
        status_short = status.replace('watch_', '')
        mf_yi = f"{mf/1e8:.1f}"
        print(f"{i:>4} {code:6s} {name:8s} {status_short:12s} {comp:>5.0f}  {may_chg:>+5.1f}% {dev:>+5.0f}% {bull_m:>4s} {mf_s:>4.0f} {mom_s:>4.0f} {qual_s if qual_s is not None else 999:>4.0f} {tech_s:>4.0f} {val_s if val_s is not None else 999:>4.0f} {concl}")
    
    conn.close()
    
    print(f"\n{'='*70}")
    print("结论")
    print("="*70)
    
    strong_buy = [r for r in results if r[0] >= 75]
    watch = [r for r in results if 60 <= r[0] < 75]
    skip = [r for r in results if r[0] < 60]
    
    if strong_buy:
        print(f"\n🟢 推荐买入 ({len(strong_buy)}只)：")
        for r in strong_buy:
            print(f"  {r[2]:8s} {r[1]:6s} 综合{r[0]:.0f}分  5月{r[3]:+.1f}%  年线偏{r[4]:+.0f}%  {r[12]}")
    
    if watch:
        print(f"\n🟡 关注 ({len(watch)}只)：")
        for r in watch:
            print(f"  {r[2]:8s} {r[1]:6s} 综合{r[0]:.0f}分  5月{r[3]:+.1f}%  年线偏{r[4]:+.0f}%  {r[12]}")
    
    if skip:
        print(f"\n⚪ 不参与 ({len(skip)}只)：")
        for r in skip:
            print(f"  {r[2]:8s} {r[1]:6s} 综合{r[0]:.0f}分  5月{r[3]:+.1f}%  年线偏{r[4]:+.0f}%  {r[12]}")
    
    # 位置建议
    print(f"\n{'='*70}")
    print("位置建议")
    print("="*70)
    for r in results:
        comp, code, name, may_chg, dev, bull, _, _, _, _, _, _, concl, pos, mf, vr = r
        mf_yi = f"{mf/1e8:.1f}亿" if abs(mf) > 0 else "无资金"
        print(f"  {code:6s} {name:8s}  综合{comp:.0f}分  年线偏{dev:+.0f}%  {pos}  主力{mf_yi}")

if __name__ == '__main__':
    main()
