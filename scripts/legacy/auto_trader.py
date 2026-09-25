#!/usr/bin/env python3
"""自动模拟交易 v2 — 分批建仓/减仓"""
import os, sys, json, subprocess, time, urllib.request, http.cookiejar
import numpy as np
from datetime import datetime, date
from pathlib import Path
from urllib.request import Request, urlopen
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'stock.db'
LOG_PATH = BASE / 'auto_trade_log.json'
TRADE_URL = 'http://localhost:8080'
INITIAL_CAPITAL = 1000000
MAX_POSITIONS = 5

def login():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return op

def get(op, p): return json.loads(op.open(Request(f'{TRADE_URL}{p}')).read())
def post(op, p, d):
    return json.loads(op.open(Request(f'{TRADE_URL}{p}', data=json.dumps(d).encode(),
        headers={'Content-Type':'application/json'})).read())

def get_signals():
    r = subprocess.run([sys.executable, str(BASE/'scripts/combined_score.py')],
        capture_output=True, text=True, cwd=str(BASE), timeout=60)
    ss = []
    for line in r.stdout.split('\n'):
        parts = line.strip().split()
        if len(parts)>=6 and parts[0].isdigit():
            try:
                dv = 0
                for p in parts:
                    if '%' in p and '+' in p:
                        try: dv = float(p.replace('%',''))
                        except: pass
                        break
                ss.append({'code':parts[1],'name':parts[2],
                    'score':float(parts[3]),'reg_pred':float(parts[5].replace('%','')),'dev':dv})
            except: continue
    return ss

def price(code, retries=2):
    """获取实时价格，含重试和日志。Sina API 连续失败后返回 None 而不是静默跳过。"""
    pf = 'sz' if code.startswith(('0','3','001')) else 'sh'
    for attempt in range(retries + 1):
        try:
            resp = urllib.request.urlopen(
                f'https://hq.sinajs.cn/list={pf}{code}',
                headers={'Referer':'https://finance.sina.com.cn'}, timeout=5)
            v = resp.read().decode('gbk').split('"')[1].split(',')
            if len(v) > 3 and v[3]:
                return float(v[3])
            else:
                print(f"  ⚠️ price({code}): 返回数据不完整", file=sys.stderr)
        except Exception as e:
            if attempt < retries:
                time.sleep(1)
                continue
            print(f"  ❌ price({code}): {e}", file=sys.stderr)
    return None

def get_broad_industry(code):
    """查 stock_info 表获取行业分组（取前3位，如 C39=半导体, C35=设备, B09=采矿）"""
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        r = conn.execute(f"SELECT industry FROM stock_info WHERE stock_code='{code}'").fetchone()
        conn.close()
        if r and r[0] and len(r[0]) >= 3:
            return r[0][:3]  # 取前3位作为分组
    except: pass
    return 'ZZZ'  # 未知行业

def check_industry_limit(code, held_codes, max_same=3):
    """买入前检查同行业大类持仓数是否超限"""
    ind = get_broad_industry(code)
    same = 0
    for c in held_codes:
        if get_broad_industry(c) == ind:
            same += 1
    return same < max_same, ind, same

def get_market_style():
    """三因子连续风险评分 (0-1): 趋势(40%) + 波动率(30%) + 量价确认(30%)
    返回: risk_score (0-1, 1=正常仓位, 0=极度避险)
    """
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        rows = conn.execute("""
            SELECT close, volume, amount FROM index_daily 
            WHERE index_code='000001' ORDER BY date DESC LIMIT 120
        """).fetchall()
        conn.close()
        if len(rows) < 120:
            return 1.0, 'data_insufficient'
        
        closes = [float(r[0]) for r in rows][::-1]
        vols = [float(r[1]) if r[1] else 0 for r in rows][::-1]
        price = closes[-1]
        
        # 因子1: MA60 趋势 (40%)
        ma60_now = sum(closes[-60:]) / 60
        ma60_prev = sum(closes[-80:-20]) / 60 if len(closes) >= 80 else ma60_now
        slope = (ma60_now / ma60_prev - 1) * 100
        # sigmoid 平滑映射: slope=1%→0.5, slope=3%→0.9
        trend_score = 1.0 / (1.0 + np.exp(-(slope - 1.0) * 1.5))
        
        # 因子2: 波动率分位 (30%) — 高波动→低分
        rets = [(closes[i]/closes[i-1]-1)*100 for i in range(1, len(closes))]
        vol_20d = np.std(rets[-20:]) * np.sqrt(252) if len(rets) >= 20 else 20
        # 历史波动率分位（粗略估计：A股年化波动通常15-35%）
        vol_score = max(0, min(1, 1 - (vol_20d - 15) / 25))
        
        # 因子3: 量价确认 (30%) — 价涨量增=好，价跌量缩=差
        ma5_vol = sum(vols[-5:])/5 if len(vols)>=5 else sum(vols)/len(vols)
        ma20_vol = sum(vols[-20:])/20
        vol_ratio = ma5_vol / ma20_vol if ma20_vol > 0 else 1
        ma5_price = sum(closes[-5:])/5
        ma20_price = sum(closes[-20:])/20
        price_ratio = ma5_price / ma20_price
        # 量价同向=确认，反向=矛盾
        if (vol_ratio > 1 and price_ratio > 1) or (vol_ratio < 1 and price_ratio < 1):
            confirm_score = 1.0
        else:
            confirm_score = 0.5
        
        risk_score = trend_score * 0.40 + vol_score * 0.30 + confirm_score * 0.30
        
        # 分类标签
        if risk_score >= 0.7:
            label = 'bull'
        elif risk_score >= 0.4:
            label = 'sideways'
        else:
            label = 'bear'
        
        return risk_score, label
    except:
        return 1.0, 'sideways'

def calc_position_pct(score, style_coef=1.0):
    """4档仓位梯度 × 风格系数"""
    if score >= 80:
        base = 0.25
        method = '高置信25%'
    elif score >= 70:
        base = 0.18
        method = '中高置信18%'
    elif score >= 60:
        base = 0.12
        method = '中等置信12%'
    else:
        base = 0.07
        method = '试探仓7%'
    return base * style_coef, method

def load_log():
    if LOG_PATH.exists(): return json.loads(LOG_PATH.read_text())
    return {'daily_logs':[],'position_logs':{},'created_at':str(datetime.now())}

def save_log(l): LOG_PATH.write_text(json.dumps(l, ensure_ascii=False, indent=2))

def main():
    today = str(date.today())
    print("="*60)
    print(f"🤖 自动模拟交易 v2 — {today}")
    print("="*60)
    
    op = login()
    print("  ✅ 登录成功")
    
    signals = get_signals()
    smap = {s['code']:s for s in signals}
    print(f"  ✅ {len(signals)} 只信号")
    for s in signals:
        print(f"    {s['code']} {s['name']:8s} 融合{s['score']:.0f}  回归{s['reg_pred']:+.1f}%  年线{s['dev']:+.0f}%")
    
    st = get(op, '/api/status')
    cash = st.get('cash',0)
    pos = st.get('positions',[])
    print(f"\n💰 现金: {cash:,.0f}  持仓: {len(pos)}/{MAX_POSITIONS}")
    
    log = load_log()
    plog = log.get('position_logs',{})
    daily = {'date':today,'buys':[],'sells':[],'partial_sells':[]}
    
    # ── 卖出（三层止损）──
    print("\n🔴 检查卖出...")
    for p in pos:
        code = p['code']
        nm = p['name']
        cost = p['avg_cost']
        sh = p['shares']
        pr = price(code)
        if not pr: continue
        pnl = (pr/cost-1)*100
        sig = smap.get(code)
        pl = plog.get(code,{})
        init_sh = pl.get('initial_shares',sh)
        half = sh < init_sh*0.75
        
        # ATR计算
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        rows = conn.execute(f"""
            SELECT high, low, close FROM stock_daily 
            WHERE stock_code='{code}' ORDER BY date DESC LIMIT 15
        """).fetchall()
        conn.close()
        atr = 0
        if len(rows) >= 15:
            trs = []
            for i in range(14):
                h,l,pc = float(rows[i][0]), float(rows[i][1]), float(rows[i+1][2])
                trs.append(max(h-l, abs(h-pc), abs(l-pc)))
            atr = sum(trs)/14
        
        # 均线位置
        conn2 = duckdb.connect(str(DB_PATH), read_only=True)
        cls = conn2.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 120
        """).fetchall()
        conn2.close()
        if len(cls) >= 60:
            c_arr = [float(r[0]) for r in cls][::-1]
            ma20 = sum(c_arr[-20:])/20 if len(c_arr)>=20 else sum(c_arr)/len(c_arr)
            ma60 = sum(c_arr[-60:])/60
            ma120 = sum(c_arr)/len(c_arr)
            ma5 = sum(c_arr[-5:])/5 if len(c_arr)>=5 else 0
            ma10 = sum(c_arr[-10:])/10 if len(c_arr)>=10 else 0
            bull = ma5 > ma20 > ma60
            dev_ma60 = (pr/ma60-1)*100
            dev_ma120 = (pr/ma120-1)*100
        else:
            bull, dev_ma60, dev_ma120 = True, 0, 0
        
        # 判断板块
        board = 'main'
        if code.startswith(('300','301')): board = 'gem'
        elif code.startswith(('688','689')): board = 'star'
        elif code.startswith(('4','8')): board = 'bj'
        if 'ST' in nm.upper():
            board = 'st' if datetime.now() < datetime(2026, 7, 6) else 'main'
        
        board_hard_loss = {'st':-5, 'main':-12, 'gem':-12, 'star':-12, 'bj':-12}
        board_deep = {'st':-10, 'main':-20, 'gem':-25, 'star':-25, 'bj':-20}
        board_ma120 = {'st':-7, 'main':-10, 'gem':-15, 'star':-15, 'bj':-10}
        hard_loss = board_hard_loss.get(board, -12)
        deep = board_deep.get(board, -20)
        ma120_half = board_ma120.get(board, -10)
        
        # 层级1: 技术破位 → 不等止损直接走
        if not bull and dev_ma60 < deep:
            r = post(op, '/api/trade', {'action':'sell','code':code,'price':pr})
            daily['sells'].append({'code':code,'reason':'技术破位清仓','pnl':pnl})
            msg = r.get('msg','')
            print(f"  💀 {code} {nm} [{board}]均线空排+破MA60{dev_ma60:.0f}% → {'✅' if r.get('ok') else f'❌ {msg}'}")
            continue
        
        if dev_ma60 < deep or dev_ma120 < deep:
            r = post(op, '/api/trade', {'action':'sell','code':code,'price':pr})
            daily['sells'].append({'code':code,'reason':'深度破位','pnl':pnl})
            msg = r.get('msg','')
            print(f"  💀 {code} {nm} [{board}]深度破位(MA60={dev_ma60:.0f}%,MA120={dev_ma120:.0f}%) → {'✅' if r.get('ok') else f'❌ {msg}'}")
            continue
        
        if dev_ma120 < ma120_half:
            h = sh//2
            r = post(op, '/api/trade', {'action':'sell','code':code,'price':pr,'shares':h})
            daily['sells'].append({'code':code,'reason':'破MA120减半','pnl':pnl})
            msg = r.get('msg','')
            print(f"  📉 {code} {nm} [{board}]破MA120({dev_ma120:.0f}%) 卖{h}股 → {'✅' if r.get('ok') else f'❌ {msg}'}")
            continue
        
        # 层级2: ATR止损
        if atr > 0 and pnl < -(atr/cost*2*100):
            r = post(op, '/api/trade', {'action':'sell','code':code,'price':pr})
            daily['sells'].append({'code':code,'reason':f'ATR止损(atr={atr:.2f})','pnl':pnl})
            msg = r.get('msg','')
            print(f"  💀 {code} {nm} ATR止损({pnl:.1f}%) → {'✅' if r.get('ok') else f'❌ {msg}'}")
            continue
        
        # 硬止损（按板块）
        if pnl < hard_loss:
            r = post(op, '/api/trade', {'action':'sell','code':code,'price':pr})
            daily['sells'].append({'code':code,'reason':'硬止损','pnl':pnl})
            msg = r.get('msg','')
            print(f"  💀 {code} {nm} [{board}]硬止损{pnl:.1f}% → {'✅' if r.get('ok') else f'❌ {msg}'}")
            continue
        
        # 达目标卖一半
        tg = p.get('target',0)
        if tg and pr>=tg and not half:
            h = sh//2
            r = post(op, '/api/trade', {'action':'sell','code':code,'price':pr,'shares':h})
            daily['partial_sells'].append({'code':code,'reason':'目标锁利'})
            msg = r.get('msg','')
            print(f"  🎯 {code} {nm} 达目标{tg} 卖{h}股 → {'✅' if r.get('ok') else f'❌ {msg}'}")
            continue
        
        # 信号转负分批卖
        if sig and sig['score']<55:
            if half:
                r = post(op, '/api/trade', {'action':'sell','code':code,'price':pr})
                daily['sells'].append({'code':code,'reason':'信号转负清仓','pnl':pnl})
                msg = r.get('msg','')
                print(f"  📉 {code} {nm} 信号{sig['score']:.0f} 清仓(已半仓) → {'✅' if r.get('ok') else f'❌ {msg}'}")
            else:
                h = sh//2
                r = post(op, '/api/trade', {'action':'sell','code':code,'price':pr,'shares':h})
                daily['partial_sells'].append({'code':code,'reason':'信号转负减半'})
                msg = r.get('msg','')
                print(f"  📉 {code} {nm} 信号{sig['score']:.0f} 卖{h}股 → {'✅' if r.get('ok') else f'❌ {msg}'}")
            continue
    
    time.sleep(0.5)
    st = get(op, '/api/status')
    cash = st.get('cash',0)
    pos = st.get('positions',[])
    held = {p['code']:p for p in pos}
    
    # ── 买入 ──
    print("\n🟢 检查买入...")
    
    # 市场风格检测
    risk_score, style_label = get_market_style()
    icons = {'bull':'🐂 牛市', 'bear':'🐻 熊市', 'sideways':'📊 震荡'}
    label_disp = icons.get(style_label, '📊 震荡')
    print(f"  风险评分: {risk_score:.2f} ({label_disp}) 仓位系数 ×{risk_score:.2f}")
    
    slots = MAX_POSITIONS - len(pos)
    if slots>0 and cash>=10000:
        held_codes = list(held.keys())
        cands = []
        skipped_industry = []
        for s in signals:
            if s['code'] in held: continue
            if s['score']<55: continue
            if s['dev']>20:
                print(f"  ⚠️ {s['name']}({s['code']}) 年线偏{s['dev']:+.0f}% >20%，跳过")
                continue
            
            # 行业集中度检查
            ok, ind, same_cnt = check_industry_limit(s['code'], held_codes)
            if not ok:
                skipped_industry.append(f"{s['name']}({ind}{same_cnt}只)")
                continue
            
            pct, method = calc_position_pct(s['score'], risk_score)
            cands.append((s, method, pct))
        
        if skipped_industry:
            print(f"  ⛔ 行业超限跳过: {', '.join(skipped_industry)}")
        
        cands.sort(key=lambda x:x[0]['score'], reverse=True)
        cands = cands[:slots]
        
        for s, method, pct in cands:
            pr = price(s['code'])
            if not pr: continue
            amt = min(cash * pct / 0.25, INITIAL_CAPITAL * pct)
            sh = max(int(amt/pr/100)*100, 100)
            r = post(op, '/api/trade', {'action':'buy','code':s['code'],
                'name':s['name'],'price':pr,'shares':sh})
            if r.get('ok'):
                daily['buys'].append({'code':s['code'],'method':method,'shares':sh})
                plog[s['code']] = {'initial_shares':sh,'buy_date':today}
                held_codes.append(s['code'])  # 加入已持仓列表，后续行业检查生效
                print(f"  📈 {s['code']} {s['name']:8s} {method}(实际{pct*100:.0f}%) {sh}股  ✅")
            else:
                print(f"  📈 {s['code']} {s['name']:8s} {method}  ❌ {r.get('msg','')}")
            time.sleep(0.5)
    
    # 补仓价记录
    for p in pos:
        code = p['code']
        sig = smap.get(code)
        if sig and 55<=sig['score']<70 and p['shares']<200:
            fp = round(p['avg_cost']*0.95, 2)
            plog[code] = plog.get(code,{})
            plog[code]['fill_price'] = fp
            plog[code]['fill_shares'] = 200 - p['shares']
    
    log['daily_logs'].append(daily)
    log['position_logs'] = plog
    save_log(log)
    
    try: get(op, '/api/update_nav')
    except: pass
    
    st = get(op, '/api/status')
    cash = st.get('cash',0)
    pos = st.get('positions',[])
    
    print(f"\n{'='*60}")
    print("📋 今日操作")
    print(f"{'='*60}")
    print(f"  买入: {len(daily['buys'])}笔 减仓: {len(daily['partial_sells'])}笔 清仓: {len(daily['sells'])}笔")
    print(f"\n💰 收盘: 现金{cash:,.0f}  持仓{len(pos)}只")
    tp = 0
    for p in pos:
        pnl = p.get('pnl_pct',0)
        tp += pnl
        print(f"    {p['code']} {p['name']:8s} {p['shares']}股  盈亏{pnl:+.1f}%")
    if pos: print(f"  平均: {tp/len(pos):+.1f}%")
    
    st['date'] = today
    log['last_snapshot'] = st
    save_log(log)

if __name__ == '__main__':
    main()
