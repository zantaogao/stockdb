#!/usr/bin/env python3
"""
自动选股评分 → 更新观察名单 + 记录每日快照

盘后17:35执行:
1. 调复盘.py → 候选列表
2. 调scoring.py → 评分筛选
3. 更新 holdings.json watch 列表
4. 记录每日快照到 stock_tracking.json
5. 同步 simulate.py
"""
import os, sys, json, subprocess, re, duckdb
from datetime import datetime, date, timedelta
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
SCRIPTS = BASE / 'scripts'
DB_PATH = BASE / 'stock.db'
HOLD_PATH = BASE / 'holdings.json'
TRACK_PATH = BASE / 'stock_tracking.json'
SIMULATE_PY = BASE / 'simulate.py'

SCORE_THRESHOLD = 75  # 评分阈值
MAX_CANDIDATES = 10   # 最多入选数量

MOVING_AVERAGES = [5, 10, 20, 60, 120]

# ── 工具 ──────────────────────────────────────────────

def load_json(path, default=None):
    if default is None: default = {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except:
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def get_db():
    return duckdb.connect(str(DB_PATH), read_only=True)

def is_trading_day():
    """粗略判断是否交易日：非周末"""
    return datetime.now().weekday() < 5

# ── 运行复盘 + 评分 ──────────────────────────────────

def run_fupan():
    """运行复盘.py --mode long，提取候选股票代码"""
    fupan_py = SCRIPTS / '复盘.py'
    if not fupan_py.exists():
        log("❌ 复盘.py 不存在")
        return []
    
    try:
        result = subprocess.run(
            [sys.executable, str(fupan_py), '--mode', 'long'],
            capture_output=True, text=True, timeout=120,
            cwd=str(SCRIPTS),
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        output = result.stdout + result.stderr
        
        # 从输出提取候选 — 只取【候选股】/【中长线候选股】章节后的6位代码
        candidates = []
        in_candidate_section = False
        
        for line in output.split('\n'):
            # 检测进入候选股章节
            if re.search(r'候选股|候选', line):
                in_candidate_section = True
                continue
            # 如果进入下一个章节（以【开头）或到末尾，退出候选模式
            if in_candidate_section and re.match(r'^【|^===|^⚠', line):
                in_candidate_section = False
                continue
            # 只在候选章节内提取6位代码
            if in_candidate_section:
                codes = re.findall(r'\b(\d{6})\b', line)
                for c in codes:
                    if c.startswith(('00','30','60','68')) and c not in ('000001','399001','399006'):
                        if c not in candidates:
                            candidates.append(c)
        
        log(f"📡 复盘候选: {len(candidates)} 只")
        return candidates[:30]  # 最多30只候选
    except subprocess.TimeoutExpired:
        log("⏰ 复盘.py 超时")
        return []
    except Exception as e:
        log(f"❌ 复盘异常: {e}")
        return []

def run_scoring(code):
    """运行 scoring.py 对单只股票评分"""
    scoring_py = SCRIPTS / 'scoring.py'
    if not scoring_py.exists():
        return None, None
    
    try:
        result = subprocess.run(
            [sys.executable, str(scoring_py), code, '--mode', 'long'],
            capture_output=True, text=True, timeout=60,
            cwd=str(SCRIPTS),
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        output = result.stdout + result.stderr
        
        # 提取总分
        score_match = re.search(r'总分\s*([\d.]+)', output)
        score = float(score_match.group(1)) if score_match else None
        
        # 提取各维度分数
        details = {}
        for line in output.split('\n'):
            m = re.match(r'(.+?)\s*[:：]\s*([\d.]+)\s*分', line)
            if m:
                details[m.group(1).strip()] = float(m.group(2))
        
        return score, details
    except Exception as e:
        log(f"  ⚠️ {code} 评分异常: {e}")
        return None, None

# ── 获取每日数据 ──────────────────────────────────────

def get_daily_snapshot(code):
    """从 stock.db 获取该股最新交易日的快照数据"""
    try:
        db = get_db()
        # 最新收盘
        latest = db.execute(f"""
            SELECT date, close, change_pct, volume, amount
            FROM stock_daily WHERE stock_code='{code}'
            ORDER BY date DESC LIMIT 1
        """).fetchone()
        if not latest:
            db.close()
            return None
        
        d = latest[0]
        today_str = d.isoformat() if hasattr(d, 'isoformat') else str(d)
        close = float(latest[1]) if latest[1] else 0
        change = float(latest[2]) if latest[2] else 0
        volume = float(latest[3]) if latest[3] else 0
        
        # 计算MA
        prices = db.execute(f"""
            SELECT close FROM stock_daily 
            WHERE stock_code='{code}' AND date<='{today_str}'
            ORDER BY date DESC LIMIT {max(MOVING_AVERAGES)}
        """).fetchall()
        closes = [float(r[0]) for r in prices if r[0]]
        
        ma_values = {}
        for n in MOVING_AVERAGES:
            if len(closes) >= n:
                ma_values[f'ma{n}'] = round(sum(closes[:n]) / n, 2)
            else:
                ma_values[f'ma{n}'] = None
        
        # 均量 (20日)
        vols = db.execute(f"""
            SELECT volume FROM stock_daily 
            WHERE stock_code='{code}' AND date<='{today_str}'
            ORDER BY date DESC LIMIT 20
        """).fetchall()
        vol_values = [float(r[0]) for r in vols if r[0] and float(r[0]) > 0]
        avg_vol_20 = sum(vol_values) / len(vol_values) if vol_values else 1
        vol_ratio = round(volume / avg_vol_20, 2) if avg_vol_20 > 0 else None
        
        # 主力资金（当日）
        mf = db.execute(f"""
            SELECT main_net FROM money_flow 
            WHERE stock_code='{code}' AND date='{today_str}'
        """).fetchone()
        money_flow = round(float(mf[0]), 2) if mf and mf[0] else None
        
        db.close()
        
        return {
            "date": today_str,
            "close": close,
            "change_pct": change,
            "volume_ratio": vol_ratio,
            "money_flow": money_flow,
            **ma_values,
        }
    except Exception as e:
        log(f"  ⚠️ {code} 快照异常: {e}")
        return None

# ── 技术分析点评 ──────────────────────────────────────

def generate_analysis_note(code, snap, prev_snap=None):
    """基于技术指标生成详细每日分析点评"""
    if not snap:
        return ""
    
    close = snap.get('close', 0)
    change = snap.get('change_pct', 0)
    vol_ratio = snap.get('volume_ratio')
    mf = snap.get('money_flow')
    ma5 = snap.get('ma5')
    ma10 = snap.get('ma10')
    ma20 = snap.get('ma20')
    ma60 = snap.get('ma60')
    ma120 = snap.get('ma120')
    
    parts = []
    
    # 1. 涨跌方向与幅度
    if change > 5: parts.append(f"🔥暴涨{change:.1f}%")
    elif change > 3: parts.append(f"大涨{change:.1f}%")
    elif change > 1: parts.append(f"上涨{change:.1f}%")
    elif change < -5: parts.append(f"💥暴跌{change:.1f}%")
    elif change < -3: parts.append(f"大跌{change:.1f}%")
    elif change < -1: parts.append(f"下跌{change:.1f}%")
    else: parts.append(f"平盘{change:+.1f}%")
    
    # 2. 量能分析
    if vol_ratio is not None:
        if vol_ratio > 3.0: parts.append(f"巨量(×{vol_ratio:.1f})" + ("🚀" if change > 0 else "💨"))
        elif vol_ratio > 2.0: parts.append(f"放量(×{vol_ratio:.1f})" + ("📈" if change > 0 else "📉"))
        elif vol_ratio > 1.5: parts.append(f"量升(×{vol_ratio:.1f})")
        elif vol_ratio < 0.3: parts.append(f"地量(×{vol_ratio:.1f})💤")
        elif vol_ratio < 0.5: parts.append(f"缩量(×{vol_ratio:.1f})")
        elif vol_ratio < 0.7: parts.append(f"量能不足(×{vol_ratio:.1f})")
    
    # 3. 均线位置
    ma_info = []
    if ma5 is not None:
        dev5 = (close - ma5) / ma5 * 100
        if abs(dev5) < 0.5: ma_info.append(f"MA5={ma5:.2f}贴线")
        elif dev5 > 0: ma_info.append(f"MA5={ma5:.2f}上{dev5:.1f}%")
        else: ma_info.append(f"MA5={ma5:.2f}下{abs(dev5):.1f}%")
    if ma20 is not None:
        dev20 = (close - ma20) / ma20 * 100
        if abs(dev20) < 0.5: ma_info.append(f"MA20={ma20:.2f}贴线")
        elif dev20 > 0: ma_info.append(f"MA20={ma20:.2f}上{dev20:.1f}%")
        else: ma_info.append(f"MA20={ma20:.2f}下{abs(dev20):.1f}%")
    if ma60 is not None:
        dev60 = (close - ma60) / ma60 * 100
        if close > ma60: ma_info.append(f"MA60={ma60:.2f}+{abs(dev60):.1f}%")
        else: ma_info.append(f"MA60={ma60:.2f}-{abs(dev60):.1f}%")
    if ma120 is not None:
        dev120 = (close - ma120) / ma120 * 100
        if close > ma120: ma_info.append(f"MA120={ma120:.2f}+{abs(dev120):.1f}%")
        else: ma_info.append(f"MA120={ma120:.2f}-{abs(dev120):.1f}%")
    if ma_info:
        parts.append(" | ".join(ma_info))
    
    # 4. 均线排列
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60: parts.append("✅多头排列(5>20>60)")
        elif ma5 < ma20 < ma60: parts.append("⚠️空头排列(5<20<60)")
        elif ma5 > ma20 and close > ma5: parts.append("短期偏多(5>20)")
        elif ma5 < ma20 and close < ma5: parts.append("短期偏空(5<20)")
    
    # 5. 资金流
    if mf is not None:
        mf_yi = mf / 100000000
        if mf_yi > 1: parts.append(f"💰主力净流入+{mf_yi:.1f}亿🔥")
        elif mf_yi > 0.3: parts.append(f"主力流入+{mf_yi:.1f}亿")
        elif mf_yi > 0: parts.append(f"主力微流入+{mf_yi:.1f}亿")
        elif mf_yi < -1: parts.append(f"💰主力净流出{mf_yi:.1f}亿💥")
        elif mf_yi < -0.3: parts.append(f"主力流出{mf_yi:.1f}亿")
        else: parts.append(f"主力微流出{mf_yi:.1f}亿")
    
    # 6. 关键信号
    signals = []
    if prev_snap is not None and 'close' in prev_snap:
        pc = prev_snap.get('close', 0)
        if pc and ma60 and pc < ma60 and close >= ma60: signals.append("突破MA60!✅")
        elif pc and ma120 and pc < ma120 and close >= ma120: signals.append("突破MA120!✅")
        elif pc and ma60 and pc >= ma60 and close < ma60: signals.append("跌破MA60⚠️")
        elif pc and ma120 and pc >= ma120 and close < ma120: signals.append("跌破MA120⚠️")
        prev_cp = prev_snap.get('change_pct', 0)
        if change > 0 and prev_cp > 0: signals.append("连涨")
        elif change < 0 and prev_cp < 0: signals.append("连跌⚠️")
    
    if vol_ratio is not None and vol_ratio > 2.0 and change > 3: signals.append("放量突破📈")
    if vol_ratio is not None and vol_ratio < 0.4: signals.append("缩量整理💤")
    if signals:
        parts.append(" | ".join(signals))
    
    # 评分
    score = snap.get('score')
    if score:
        if score >= 85: parts.append(f"评分{score:.0f}★★★")
        elif score >= 75: parts.append(f"评分{score:.0f}★★")
        elif score >= 60: parts.append(f"评分{score:.0f}★")
    
    # 7. 短线判断
    if ma20 and close > ma20 and (mf is None or mf > 0):
        parts.append("短线偏多")
    elif ma20 and close < ma20 and (mf is not None and mf < -0.1):
        parts.append("短线偏空")
    
    return "，".join(parts) if parts else "正常"

# ── 更新观察名单 ──────────────────────────────────────

def update_watch_list(candidates_scores):
    """
    candidates_scores: [(code, score, details, snapshot), ...]
    更新 holdings.json 的 watch 列表
    """
    holdings = load_json(HOLD_PATH, {"positions": []})
    tracking = load_json(TRACK_PATH, {})
    today = datetime.now().strftime("%Y-%m-%d")
    
    existing_codes = {p['code'] for p in holdings['positions']}
    added = 0
    
    for code, score, details, snap in candidates_scores:
        if score is None or score < SCORE_THRESHOLD:
            continue
        if added >= MAX_CANDIDATES:
            break
        
        # 获取股票名称
        name = snap.get('name', '') if isinstance(snap, dict) else ''
        if not name:
            try:
                db = get_db()
                r = db.execute(f"SELECT stock_name FROM stock_info WHERE stock_code='{code}'").fetchone()
                name = r[0] if r else ''
                db.close()
            except:
                pass
        
        if code in existing_codes:
            # 已存在，更新数据（如果缺失）
            pos = next(p for p in holdings['positions'] if p['code'] == code)
            if pos.get('status') == 'hold':
                log(f"  ⏭️ {code} {name} 持仓中，跳过")
                continue
            
            # 更新缺失的关键价位
            updated = False
            if snap and snap.get('close'):
                if pos.get('entry_low') is None:
                    pos['entry_low'] = round(snap['close'] * 0.97, 2)
                    updated = True
                if pos.get('entry_high') is None:
                    pos['entry_high'] = round(snap['close'] * 1.03, 2)
                    updated = True
                if pos.get('stop_loss') is None and snap.get('ma60'):
                    pos['stop_loss'] = round(snap['ma60'] * 0.95, 2)
                    updated = True
                if pos.get('target') is None:
                    pos['target'] = round(snap['close'] * 1.15, 2)
                    updated = True
                if pos.get('watch_added') is None:
                    pos['watch_added'] = today
                    updated = True
            
            if updated:
                log(f"  🔄 {code} {name} 已更新关键价位")
            else:
                log(f"  ⏭️ {code} {name} 已在观察中，数据已完整")
        
        # 新加入 watch
        entry_low = round(snap['close'] * 0.97, 2) if snap and snap.get('close') else None
        entry_high = round(snap['close'] * 1.03, 2) if snap and snap.get('close') else None
        stop_loss = round(snap['ma60'] * 0.95, 2) if snap and snap.get('ma60') else None
        target = round(snap['close'] * 1.15, 2) if snap and snap.get('close') else None
        
        holdings['positions'].append({
            "code": code,
            "name": name,
            "buy_date": None,
            "buy_price": None,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop_loss,
            "target": target,
            "status": "watch",
            "watch_added": today,
            "note": f"自动选股 {today} 评分{score}",
        })
        existing_codes.add(code)
        added += 1
        
        # 初始化 tracking 记录
        if code not in tracking:
            tracking[code] = {
                "name": name,
                "watch_added": today,
                "daily": []
            }
        
        log(f"  ✅ {code} {name} 评分{score} → 加入观察")
    
    if added > 0:
        save_json(HOLD_PATH, holdings)
    log(f"📋 观察名单更新: 新增 {added} 只")
    
    # 更新 tracking 快照
    for code, score, details, snap in candidates_scores:
        if code not in tracking:
            continue
        if not snap:
            continue
        
        entry = {
            "date": snap.get('date', today),
            "close": snap.get('close'),
            "change_pct": snap.get('change_pct'),
            "volume_ratio": snap.get('volume_ratio'),
            "score": score,
            "money_flow": snap.get('money_flow'),
            "ma5": snap.get('ma5'),
            "ma10": snap.get('ma10'),
            "ma20": snap.get('ma20'),
            "ma60": snap.get('ma60'),
            "ma120": snap.get('ma120'),
        }
        
        # 生成分析点评
        prev_daily = tracking[code].get('daily', [])
        prev_snap = prev_daily[-1] if len(prev_daily) >= 1 else None
        entry['note'] = generate_analysis_note(code, entry, prev_snap)
        
        # 去重：同一日期不重复加
        existing_dates = {d['date'] for d in tracking[code]['daily']}
        if entry['date'] not in existing_dates:
            tracking[code]['daily'].append(entry)
        
        # 也更新已有持仓的快照
        if code in existing_codes:
            pos = next((p for p in holdings['positions'] if p['code'] == code), None)
            if pos and entry['date'] not in existing_dates:
                tracking[code]['daily'].append(entry)
    
    save_json(TRACK_PATH, tracking)
    return added

# ── 更新已持仓股票的快照 ──────────────────────────────

def update_hold_snapshots():
    """对 holdings.json 中 status=hold 的持仓也抓快照"""
    holdings = load_json(HOLD_PATH, {"positions": []})
    tracking = load_json(TRACK_PATH, {})
    today = datetime.now().strftime("%Y-%m-%d")
    updated = 0
    
    for p in holdings['positions']:
        code = p['code']
        if p.get('status') != 'hold':
            continue
        
        snap = get_daily_snapshot(code)
        if not snap:
            continue
        
        if code not in tracking:
            tracking[code] = {
                "name": p.get('name', ''),
                "watch_added": p.get('watch_added', p.get('buy_date', today)),
                "daily": []
            }
        
        existing_dates = {d['date'] for d in tracking[code]['daily']}
        if snap['date'] not in existing_dates:
            entry = {
                "date": snap['date'],
                "close": snap['close'],
                "change_pct": snap['change_pct'],
                "volume_ratio": snap['volume_ratio'],
                "score": None,
                "money_flow": snap['money_flow'],
                "ma5": snap.get('ma5'),
                "ma10": snap.get('ma10'),
                "ma20": snap.get('ma20'),
                "ma60": snap.get('ma60'),
                "ma120": snap.get('ma120'),
            }
            prev_daily = tracking[code].get('daily', [])
            prev_snap = prev_daily[-1] if len(prev_daily) >= 1 else None
            entry['note'] = generate_analysis_note(code, entry, prev_snap)
            tracking[code]['daily'].append(entry)
            updated += 1
    
    save_json(TRACK_PATH, tracking)
    log(f"📸 持仓快照更新: {updated} 条")
    return updated

# ── 同步模拟交易系统 ──────────────────────────────────

def sync_simulate():
    """调用 simulate.py 的同步接口"""
    try:
        import urllib.request
        url = "http://localhost:8081/api/sync"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if result.get('ok'):
            log("🔄 模拟交易系统同步成功")
        else:
            log(f"⚠️ 模拟交易同步: {result.get('msg', '未知')}")
        
        # 同时更新净值
        url2 = "http://localhost:8081/api/update_nav"
        req2 = urllib.request.Request(url2)
        resp2 = urllib.request.urlopen(req2, timeout=10)
        log("📊 模拟交易净值已更新")
        
    except Exception as e:
        log(f"⚠️ 模拟交易同步失败 (服务未启动?): {e}")

# ── 主流程 ────────────────────────────────────────────

def main():
    if not is_trading_day():
        log("📅 非交易日，跳过")
        return
    
    log("🚀 自动选股评分 + 观察名单更新 开始")
    
    # Step 1: 获取候选
    candidates = run_fupan()
    if not candidates:
        log("⚠️ 无候选，但仍更新持仓快照")
        update_hold_snapshots()
        return
    
    # Step 2: 逐股评分
    scored = []
    for code in candidates:
        score, details = run_scoring(code)
        snap = get_daily_snapshot(code)
        log(f"  📊 {code} 评分: {score}")
        scored.append((code, score, details, snap))
    
    # 按评分降序
    scored.sort(key=lambda x: x[1] or 0, reverse=True)
    
    # Step 3: 更新观察名单
    added = update_watch_list(scored)
    
    # Step 4: 更新持仓快照
    update_hold_snapshots()
    
    # Step 5: 同步 simulate.py
    sync_simulate()
    
    log(f"✅ 完成: 候选{len(candidates)}只 → 新增观察{added}只")

if __name__ == '__main__':
    main()
