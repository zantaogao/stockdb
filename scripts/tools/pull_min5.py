#!/usr/bin/env python3
"""拉取5分钟K线并计算分钟级因子"""
import duckdb, os, json, urllib.request, time
from datetime import datetime, date
from pathlib import Path

DB_DIR = Path.home() / '.hermes' / 'stockdb'
DB = str(DB_DIR / 'stock.db')

def fetch_min5(code, date_str=None, max_bars=240):
    """从新浪拉取5分钟K线"""
    market = "sz" if code.startswith("00") or code.startswith("30") else "sh"
    if code.startswith("688") or code.startswith("689"):
        market = "sh"
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={market}{code}&scale=5&ma=no&datalen={max_bars}"
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10).read()
        raw = resp.decode("utf-8", errors="replace")
        if raw.strip() == "null" or not raw.strip().startswith("["):
            return []
        data = json.loads(raw)
        # 如果指定日期则只保留该日
        if date_str:
            data = [d for d in data if d.get("day","").startswith(date_str)]
        return data
    except Exception as e:
        return []

def compute_min5_factors(bars, code, date_str):
    """
    从5分钟K线计算因子
    返回因子字典
    """
    if not bars or len(bars) < 10:
        return None
    
    n = len(bars)
    opens = [float(b["open"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close"]) for b in bars]
    volumes = [int(b["volume"]) if b["volume"] else 0 for b in bars]
    
    total_vol = sum(volumes)
    total_range = max(highs) - min(lows)
    
    if total_vol == 0:
        return None
    
    # 开盘集中度: 前30分钟(6根)成交量占比
    open_vol_ratio = sum(volumes[:6]) / total_vol if total_vol > 0 else 0
    
    # 上午/下午成交量比 (上午=前24根, 下午=后24根)
    mid = n // 2
    am_vol = sum(volumes[:mid])
    pm_vol = sum(volumes[mid:])
    am_pm_ratio = am_vol / pm_vol if pm_vol > 0 else 1
    
    # 尾盘动量: 最后60分钟(12根)涨跌幅
    tail_return = (closes[-1] - closes[-13]) / closes[-13] * 100 if len(closes) >= 13 else 0
    
    # 趋势一致性: 上涨K线占比
    up_bars = sum(1 for i in range(1, n) if closes[i] > opens[i])
    up_ratio = up_bars / n if n > 0 else 0.5
    
    # 尾盘15分钟方向: 最后3根K线方向
    last_3 = [closes[i] - opens[i] for i in range(-3, 0)]
    tail_direction = sum(1 for d in last_3 if d > 0)  # 0-3
    
    # 收盘位置: 最后一根K线在当日位置
    final_close = closes[-1]
    day_high = max(highs)
    day_low = min(lows)
    close_position = (final_close - day_low) / (day_high - day_low) * 100 if day_high > day_low else 50
    
    # 成交量变异系数: 成交量离散度
    vol_mean = total_vol / n
    vol_var = sum((v - vol_mean) ** 2 for v in volumes) / n
    vol_cv = (vol_var ** 0.5) / vol_mean if vol_mean > 0 else 0
    
    # 大单密度: 单根最大成交量占比
    max_vol_ratio = max(volumes) / total_vol if total_vol > 0 else 0
    
    # 开盘跳空: 第一根K线vs前日收盘
    # bars是按时间倒序还是正序？检查
    # Sina返回按时间正序(最早->最晚)
    
    return {
        "open_vol_ratio": round(open_vol_ratio * 100, 1),     # 开盘30分钟成交量%
        "am_pm_ratio": round(am_pm_ratio, 2),                  # 上下午量比
        "tail_return": round(tail_return, 2),                  # 尾盘60分钟涨跌幅%
        "up_ratio": round(up_ratio * 100, 1),                  # 上涨K线占比%
        "tail_direction": tail_direction,                      # 尾盘15分钟方向(0-3)
        "close_position": round(close_position, 1),            # 收盘位置%
        "vol_cv": round(vol_cv, 2),                            # 成交量变异系数
        "max_vol_ratio": round(max_vol_ratio * 100, 1),        # 单根最大成交量占比%
    }


def pull_and_store(codes, date_str=None, batch_size=10):
    """批量拉取并存入DuckDB"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    conn = duckdb.connect(DB)
    # 建表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_min5 (
            stock_code VARCHAR,
            trade_date DATE,
            time_slot INTEGER,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
            open_vol_ratio DOUBLE, am_pm_ratio DOUBLE,
            tail_return DOUBLE, up_ratio DOUBLE,
            tail_direction INTEGER, close_position DOUBLE,
            vol_cv DOUBLE, max_vol_ratio DOUBLE,
            PRIMARY KEY (stock_code, trade_date)
        )
    """)
    
    pulled = 0
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        rows = []
        for code in batch:
            bars = fetch_min5(code, date_str)
            if bars:
                factors = compute_min5_factors(bars, code, date_str)
                if factors:
                    # 所有5分钟线收成一条聚合记录
                    rows.append((code, date_str,
                                 len(bars),  # time_slot复用为bar数量
                                 factors["open_vol_ratio"], factors["am_pm_ratio"],
                                 factors["tail_return"], factors["up_ratio"],
                                 factors["tail_direction"], factors["close_position"],
                                 factors["vol_cv"], factors["max_vol_ratio"]))
            pulled += 1
            if pulled % 50 == 0:
                print(f"  已拉取 {pulled}/{len(codes)}", flush=True)
            time.sleep(0.05)  # 限速
        
        # 批量写入
        if rows:
            conn.executemany("""
                INSERT OR REPLACE INTO stock_min5
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        
        time.sleep(0.5)  # 批次间隔
    
    total = conn.execute("SELECT COUNT(*) FROM stock_min5 WHERE trade_date=?", [date_str]).fetchone()[0]
    print(f"  ✅ {date_str}: 共拉取 {total} 只股票5分钟数据")
    conn.close()
    return total


def rank_with_min5(candidates, date_str, top_n=30):
    """
    用分钟级因子对候选股二次排名
    candidates: 复盘.py 输出的候选列表
    返回重排后的列表
    """
    conn = duckdb.connect(DB)
    codes = [c["code"] for c in candidates]
    
    # 取分钟因子
    rows = conn.execute(f"""
        SELECT stock_code, open_vol_ratio, am_pm_ratio, tail_return,
               up_ratio, tail_direction, close_position, vol_cv, max_vol_ratio
        FROM stock_min5
        WHERE trade_date='{date_str}' AND stock_code IN ({','.join(f"'{c}'" for c in codes)})
    """).fetchall()
    
    factors = {r[0]: {
        "open_vol_ratio": r[1], "am_pm_ratio": r[2], "tail_return": r[3],
        "up_ratio": r[4], "tail_direction": r[5], "close_position": r[6],
        "vol_cv": r[7], "max_vol_ratio": r[8]
    } for r in rows}
    
    conn.close()
    
    # 对每个候选股打分
    scored = []
    for c in candidates:
        f = factors.get(c["code"])
        if not f:
            continue
        
        score = 0
        details = []
        
        # 开盘集中度: 15~35%最健康 (太高=主力出货, 太低=无主力)
        if 15 <= f["open_vol_ratio"] <= 35:
            score += 20
            details.append(f"开集{f['open_vol_ratio']}%")
        elif 10 <= f["open_vol_ratio"] <= 45:
            score += 10
            details.append(f"开集{f['open_vol_ratio']}%")
        
        # 尾盘动量: 最后60分钟涨跌
        if f["tail_return"] > 1:
            score += 20
            details.append(f"尾盘+{f['tail_return']}%")
        elif f["tail_return"] > 0:
            score += 10
            details.append(f"尾盘+{f['tail_return']}%")
        elif f["tail_return"] < -1:
            score -= 10
            details.append(f"尾盘{f['tail_return']}%⚠️")
        
        # 趋势一致性: 上涨K线占比>55%
        if f["up_ratio"] > 60:
            score += 15
            details.append(f"涨K{f['up_ratio']}%")
        elif f["up_ratio"] > 50:
            score += 8
            details.append(f"涨K{f['up_ratio']}%")
        
        # 尾盘方向: 最后3根K线多为红
        if f["tail_direction"] >= 2:
            score += 15
            details.append(f"尾向{f['tail_direction']}/3")
        elif f["tail_direction"] == 0:
            score -= 10
            details.append(f"尾向0/3⚠️")
        
        # 收盘位置: 收在当日上1/3
        if f["close_position"] > 66:
            score += 15
            details.append(f"收位{f['close_position']}%")
        elif f["close_position"] < 33:
            score -= 5
            details.append(f"收位偏低")
        
        # 成交量变异: 适中=有节奏
        if 0.5 <= f["vol_cv"] <= 1.5:
            score += 10
        elif f["vol_cv"] > 2:
            score -= 5
            details.append("量异动")
        
        # 大单密度
        if f["max_vol_ratio"] > 15:
            score += 5
            details.append(f"大单{f['max_vol_ratio']}%")
        
        scored.append({**c, "min5_score": score, "min5_detail": " ".join(details)})
    
    # 按分钟因子分排序
    scored.sort(key=lambda x: x.get("min5_score", 0), reverse=True)
    return scored[:top_n]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # 测试: python3 pull_min5.py 300502
        code = sys.argv[1]
        bars = fetch_min5(code)
        print(f"获取 {code}: {len(bars)} 条5分钟线")
        if bars:
            f = compute_min5_factors(bars, code, "")
            if f:
                for k, v in f.items():
                    print(f"  {k}: {v}")
    else:
        print("用法: python3 pull_min5.py <股票代码>")
