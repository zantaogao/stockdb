#!/usr/bin/env python3
"""每日观察名单同步 — 复盘→评分→加入观察（含完整字段）"""
import os, sys, json, subprocess, re, duckdb, numpy as np
from datetime import date
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'stock.db'
HOLD_PATH = BASE / 'holdings.json'

def _normalize_score(sc):
    """统一评分格式：dict 取 fusion，否则原值返回"""
    if isinstance(sc, dict):
        return sc.get('fusion', 0)
    return sc

def get_fupan_candidates():
    """从 agent_picker 已运行的复盘输出中提取候选代码。
    agent_picker.py (17:30) 已经跑过 复盘.py，这里不再重复运行。
    改为读取 combined_score 的评分缓存来获取当天的候选股。"""
    # 读取 combined_score 的评分缓存（agent_picker 刚跑完）
    cache_path = BASE / '_score_cache.json'
    scores = {}
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            today_str = str(date.today())
            if cached.get('date') == today_str:
                raw_scores = cached.get('scores', {})
                # 归一化：新格式 {code: {fusion: x, ...}} → {code: fusion}
                scores = {k: _normalize_score(v) for k, v in raw_scores.items()}
        except:
            pass
    
    # 如果缓存不可用（首次或agent_picker没跑），fallback到跑combined_score
    if not scores:
        r = subprocess.run([sys.executable, str(BASE/'scripts/combined_score.py')],
            capture_output=True, text=True, cwd=str(BASE), timeout=120)
        for line in r.stdout.split('\n'):
            parts = line.strip().split()
            if len(parts)>=6 and parts[0].isdigit():
                try:
                    code=parts[1]; score=float(parts[3])
                    scores[code] = score
                except: pass
    
    # 返回评分 >= 55 的候选
    return [code for code in scores if scores[code] >= 55], scores

def enrich_stock(code):
    """查 DB 补充名称/介入区间/止损/目标"""
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    result = {'code': code, 'name': code, 'entry_low': None, 'entry_high': None,
              'stop_loss': None, 'target': None}
    
    # 名称
    name_row = conn.execute(f"SELECT stock_name, short_name FROM stock_info WHERE stock_code='{code}'").fetchone()
    if name_row:
        result['name'] = name_row[1] or name_row[0] or code
    
    # 日线数据
    rows = conn.execute(f"""
        SELECT close, volume FROM stock_daily WHERE stock_code='{code}' 
        ORDER BY date DESC LIMIT 120
    """).fetchall()
    
    if rows and len(rows) >= 20:
        closes = [r[0] for r in rows[::-1]]
        vols = [r[1] for r in rows[::-1]]
        price = closes[-1]
        
        ma20 = np.mean(closes[-20:])
        ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else ma20
        ma120 = np.mean(closes) if len(closes) >= 120 else ma60
        dev120 = (price/ma120-1)*100 if ma120 else 0
        
        # 介入区间：基于年线偏离
        if dev120 < -10:
            entry_low = round(ma120 * 0.95, 2)
            entry_high = round(ma120 * 1.05, 2)
        elif dev120 < 5:
            entry_low = round(price * 0.95, 2)
            entry_high = round(price, 2)
        elif dev120 < 15:
            entry_low = round(ma120 * 0.98, 2)
            entry_high = round(ma120 * 1.08, 2)
        else:
            entry_low = round(ma120 * 0.93, 2)
            entry_high = round(ma120 * 1.02, 2)
        
        # 止损：介入下限 * 0.85（15%回调空间）
        stop_loss = round(entry_low * 0.85, 2) if entry_low else round(price * 0.85, 2)
        
        # 目标：年线 + 20% 或 MA120 * 1.2
        target = round(ma120 * 1.2, 2) if dev120 < 30 else round(price * 1.15, 2)
        
        result['entry_low'] = entry_low
        result['entry_high'] = entry_high
        result['stop_loss'] = stop_loss
        result['target'] = target
    
    conn.close()
    return result

def main():
    print("="*50)
    print(f"观察名单同步 — {date.today()}")
    print("="*50)
    
    codes, scores = get_fupan_candidates()
    print(f"评分缓存候选: {len(codes)} 只")
    if not codes:
        print("无候选")
        return
    
    data = json.loads(HOLD_PATH.read_text()) if HOLD_PATH.exists() else {'positions': []}
    existing = {p['code'] for p in data['positions']}
    
    temps = []
    for c in codes:
        if c not in existing and c.isdigit() and len(c)==6:
            temps.append(c)
    if not temps:
        print("无新股（已全在观察名单）")
        return
    
    # scores 已从 agent_picker 的 _score_cache.json 获取，格式: {code: float_score}
    # 清理旧观察名单中的临时条目
    data['positions'] = [p for p in data['positions'] if p['code'] not in temps]
    
    added = 0
    for code in temps:
        if code not in scores: continue
        score = scores[code]
        if score < 55: continue
        
        # 补齐字段 + 查年线偏离
        info = enrich_stock(code)
        
        # 计算年线偏离（enrich_stock 内部已算，这里复用 DB 连接）
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        rows = conn.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}' 
            ORDER BY date DESC LIMIT 120
        """).fetchall()
        conn.close()
        dev = 0
        if rows and len(rows) >= 120:
            closes = [r[0] for r in rows[::-1]]
            price = closes[-1]
            ma120 = np.mean(closes)
            dev = (price/ma120 - 1) * 100 if ma120 > 0 else 0
        
        # 分级
        if score >= 70 and dev < 15:
            st, note = 'watch_active', f'一次性20% 融合{score:.0f} 年线{dev:+.0f}%'
        elif score >= 70:
            st, note = 'watch_cold', f'评分高但年线{dev:+.0f}%偏高 等回调'
        elif score >= 55 and abs(dev) <= 20:
            st, note = 'watch_active', f'分批10% 融合{score:.0f} 年线{dev:+.0f}%'
        elif score >= 55 and dev > 20:
            st, note = 'watch_cold', f'年线{dev:+.0f}%偏高 等回调'
        else:
            st, note = 'watch_cold', f'破位 年线{dev:+.0f}% 观察'
        
        entry = {
            'code': code,
            'name': info['name'],
            'status': st,
            'entry_low': info['entry_low'],
            'entry_high': info['entry_high'],
            'stop_loss': info['stop_loss'],
            'target': info['target'],
            'note': f'自动同步 {date.today()} {note}'
        }
        data['positions'].append(entry)
        added += 1
        print(f"  + {code} {info['name']:8s} {st:15s} 区间{info['entry_low']}~{info['entry_high']} 止损{info['stop_loss']} 目标{info['target']}")
    
    HOLD_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n新增 {added} 只，所有字段已补齐")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"⚠️ {e}")
