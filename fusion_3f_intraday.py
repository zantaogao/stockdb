#!/usr/bin/env python3
"""
三因子融合10d — 盘中模式
=========================
目标：盘中每5分钟用实时价格更新 fusion_3f_signals 表
策略：盘中不重算三因子，用盘后算好的 fusion_3f_score 做基础分
      根据盘中涨跌幅做动态调整

数据源：
- fusion_3f_signals 盘后基础分（存量数据）
- Sina API 实时价格（盘中实时）
- signals.db.signal_history 的 reg10（盘后算好）

写入：fusion_3f_intraday 表（独立于盘后表）

不碰现有任何表：signal_history, new_factors, flow_alpha, vol_adj 完全不动
"""

import sqlite3
import json
import time
from datetime import datetime
from pathlib import Path

STATE_DB = '/Users/zantao/.hermes/stockdb/signals.db'  # v2温层
BASE = Path(__file__).parent

# QQ 推送：最近一次强买数量（用于判断变化）
QQ_STATE_FILE = BASE / '.qq_last_qiangmai'

def _get_last_qq_state():
    """读取上次推送的强买数量"""
    try:
        return int(QQ_STATE_FILE.read_text().strip())
    except:
        return None

def _save_qq_state(n):
    """保存强买数量到文件"""
    QQ_STATE_FILE.write_text(str(n))

def push_qq(message):
    """通过 hermes send -t qqbot 发送QQ消息"""
    import subprocess
    try:
        result = subprocess.run(
            ['hermes', 'send', '-t', 'qqbot', message],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"  [QQ] ✅ 推送成功")
            return True
        else:
            print(f"  [QQ] ⚠️ 返回码: {result.returncode}, stderr: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  [QQ] ❌ 推送失败: {e}")
        return False

def send_intraday_qq(qiangmai_count, buy_count, total, prev_qiangmai, scan_time):
    """盘中强买信号变化时推送QQ（每次都推）"""
    from datetime import datetime
    now = datetime.now()
    
    # 每次都推，简单可靠
    
    # 取前10只强买信号（同分按 reg10 超卖程度排，越超卖越优先）
    import sqlite3
    conn = sqlite3.connect(STATE_DB, timeout=10)
    top_buys = conn.execute("""
        SELECT stock_code, reg10, ma_decay, flow_alpha, vol_adj, fusion_3f_score
        FROM fusion_3f_signals
        WHERE signal = '强买' AND fusion_3f_score >= 70
        ORDER BY fusion_3f_score DESC, flow_alpha DESC, reg10 ASC
        LIMIT 10
    """).fetchall()
    conn.close()
    
    lines = [f"📈 三因子融合10d信号 ({now.strftime('%H:%M')})"]
    lines.append(f"强买 {qiangmai_count} | 买 {buy_count} | 共 {total} 只")
    if prev_qiangmai is not None:
        lines.append(f"上次: {prev_qiangmai} 只")
    lines.append("")
    
    for i, r in enumerate(top_buys, 1):
        code = r[0]
        f3f = r[5]
        reg10 = r[1]
        reg10_str = f"+{reg10:.3f}" if reg10 > 0 else f"{reg10:.3f}"
        lines.append(f"  [{f3f:.0f}] {code} reg10={reg10_str} ma={r[2]:.2f} flow={r[3]:.3f}")
    
    lines.append("")
    lines.append("📌 强买=reg10<0.03且融合分高 | 盘中参考")
    
    msg = '\n'.join(lines)
    push_qq(msg)
    return True

def push_qq(message):
    """通过 hermes send -t qqbot 发送QQ消息"""
    import subprocess
    try:
        result = subprocess.run(
            ['hermes', 'send', '-t', 'qqbot', message],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"  [QQ] ✅ 推送成功")
            return True
        else:
            print(f"  [QQ] ⚠️ 返回码: {result.returncode}, stderr: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  [QQ] ❌ 推送失败: {e}")
        return False

# 盘中阈值调整
DYNAMIC_THRESHOLD = {
    'strong_buy_threshold': 0.85,
    'strong_sell_threshold': 0.65,
    'buy_threshold': 0.70,
    'sell_threshold': 0.35,
}


def get_base_signals(conn, today):
    """获取盘后计算的基础信号"""
    rows = conn.execute(f"""
        SELECT stock_code, reg10, ma_decay, flow_alpha, vol_adj, fusion_3f_score, signal
        FROM fusion_3f_signals
        WHERE REPLACE(date, '-', '') = '{today}'
        ORDER BY stock_code
    """).fetchall()
    return {r[0]: r for r in rows}


def sina_code(code):
    """Sina code mapping: 6/68/9 → sh, else sz"""
    return f"sh{code}" if code.startswith(('6', '68', '9')) else f"sz{code}"


def fetch_sina_batch(codes, timeout=5):
    """
    纯 Sina 批量获取价格，绕过 TDX。
    返回 {code: {'price': float, 'prev': float}}
    """
    try:
        import urllib.request
        sina_codes = ','.join(sina_code(c) for c in codes)
        req = urllib.request.Request(
            f"https://hq.sinajs.cn/list={sina_codes}",
            headers={"Referer": "https://finance.sina.com.cn"}
        )
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode('gbk')
        result = {}
        for line in raw.strip().split('\n'):
            if '=""' in line or 'hq_str_' not in line:
                continue
            scode = line.split('hq_str_')[1].split('=')[0]
            parts = line.split('"')[1].split(',')
            c = scode[2:] if scode.startswith(('sh', 'sz')) else scode
            price = float(parts[3]) if len(parts) > 3 and parts[3] else None
            prev = float(parts[2]) if len(parts) > 2 and parts[2] else None
            if price and c in codes:
                result[c] = {'price': price, 'prev': prev}
        return result
    except Exception as e:
        print(f"    Sina 请求失败: {e}")
        return {}


def calc_intraday_signal(base_row, change_pct):
    """
    根据盘中和涨跌幅，动态调整信号。
    """
    if not base_row:
        return '持', None

    stock_code = base_row[0]
    reg10 = base_row[1] or 0
    fusion_3f = base_row[5] or 50

    trend_factor = change_pct / 10.0  # -0.5 到 +0.5

    sb_threshold = DYNAMIC_THRESHOLD['strong_buy_threshold'] - trend_factor * 30
    ss_threshold = DYNAMIC_THRESHOLD['strong_sell_threshold'] + trend_factor * 15
    b_threshold = DYNAMIC_THRESHOLD['buy_threshold'] - trend_factor * 15
    s_threshold = DYNAMIC_THRESHOLD['sell_threshold'] + trend_factor * 10

    if reg10 < 0.03:
        if fusion_3f > sb_threshold:
            signal = '强买'
        elif fusion_3f > b_threshold:
            signal = '买'
        elif fusion_3f > b_threshold - 15:
            signal = '持'
        else:
            signal = '卖'
    elif reg10 > 0.03:
        if fusion_3f < ss_threshold:
            signal = '强卖'
        elif fusion_3f < s_threshold:
            signal = '卖'
        elif fusion_3f < s_threshold + 15:
            signal = '持'
        else:
            signal = '买'
    else:
        if fusion_3f > sb_threshold:
            signal = '买'
        elif fusion_3f < ss_threshold:
            signal = '卖'
        else:
            signal = '持'

    return signal, fusion_3f


def get_stock_list(conn):
    """获取全市场股票列表（去重）"""
    rows = conn.execute("""
        SELECT DISTINCT REPLACE(stock_code, '.', '')
        FROM signal_history
        WHERE REPLACE(date, '-', '') >= '20260701'
          AND REPLACE(date, '-', '') <= '20260726'
        ORDER BY stock_code
    """).fetchall()
    return [r[0] for r in rows if r[0]]


def run_intraday(batch_size=500):
    """
    盘中模式。
    
    流程：
    1. 获取今天盘后 fusion_3f_signals 基础分
    2. 每批 500 只，用 Sina 获取实时价格
    3. 根据涨跌幅动态调整信号
    4. 写入 fusion_3f_intraday 表
    """
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    today_clean = today.replace('-', '')

    print(f"[{now.strftime('%H:%M:%S')}] 盘中更新 fusion_3f_signals")
    print(f"  日期: {today} (clean: {today_clean})")

    conn = sqlite3.connect(STATE_DB, timeout=10)

    # 创建盘中表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fusion_3f_intraday (
            stock_code TEXT NOT NULL,
            date TEXT NOT NULL,
            scan_time TEXT NOT NULL,
            reg10 REAL,
            ma_decay REAL,
            flow_alpha REAL,
            vol_adj REAL,
            fusion_3f_score REAL,
            base_signal TEXT,
            intraday_signal TEXT,
            change_pct REAL,
            price REAL,
            is_intraday INTEGER DEFAULT 1,
            PRIMARY KEY (stock_code, date, scan_time)
        )
    """)

    # 获取股票列表
    stock_codes = get_stock_list(conn)
    print(f"  股票数: {len(stock_codes)}")

    # 获取盘后基础信号
    base_signals = get_base_signals(conn, today_clean)
    if not base_signals:
        rows = conn.execute("""
            SELECT stock_code, reg10, ma_decay, flow_alpha, vol_adj, fusion_3f_score, signal
            FROM fusion_3f_signals
            ORDER BY REPLACE(date, '-', '') DESC
            LIMIT 1000
        """).fetchall()
        base_signals = {r[0]: r for r in rows}
        print(f"  使用最近盘后记录: {len(base_signals)}只")
    else:
        print(f"  使用今日盘后记录: {len(base_signals)}只")

    update_count = 0
    scan_time = now.strftime('%H:%M:%S')

    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i:i + batch_size]
        prices = fetch_sina_batch(batch)

        for code in batch:
            base = base_signals.get(code)
            price_info = prices.get(code, {})

            if not base:
                continue

            prev_price = price_info.get('prev', 0)
            cur_price = price_info.get('price', 0)
            change_pct = ((cur_price / prev_price) - 1) * 100 if prev_price and prev_price > 0 else 0

            intraday_signal, fusion_3f = calc_intraday_signal(base, change_pct)
            base_signal = base[6] or '持'

            conn.execute("""
                INSERT OR REPLACE INTO fusion_3f_intraday
                (stock_code, date, scan_time, reg10, ma_decay, flow_alpha, vol_adj,
                 fusion_3f_score, base_signal, intraday_signal, change_pct, price, is_intraday)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, today, scan_time,
                base[1], base[2], base[3], base[4],
                base[5], base[6], intraday_signal, change_pct, cur_price, 1
            ))
            update_count += 1

        if (i + batch_size) % 1000 == 0:
            print(f"  进度: {min(i + batch_size, len(stock_codes))}/{len(stock_codes)}")

    conn.commit()

    # 清理旧盘中记录
    old_count = conn.execute(
        f"DELETE FROM fusion_3f_intraday WHERE date = '{today}' AND scan_time != '{scan_time}'"
    ).rowcount

    # 统计
    stats = conn.execute(f"""
        SELECT intraday_signal, COUNT(*)
        FROM fusion_3f_intraday
        WHERE date = '{today}' AND is_intraday = 1
        GROUP BY intraday_signal
        ORDER BY COUNT(*) DESC
    """).fetchall()

    print(f"\n  === 信号分布 ===")
    for sig, cnt in stats:
        print(f"    {sig}: {cnt} ({cnt/update_count*100:.1f}%)")

    print(f"\n  更新: {update_count} 条")
    if old_count:
        print(f"  清理: {old_count} 条旧记录")

    conn.close()
    
    # QQ 推送
    prev = _get_last_qq_state()
    qiangmai_count = stats[0][1] if stats[0][0] == '强买' else 0
    buy_count = stats[1][1] if len(stats) > 1 and stats[1][0] == '买' else 0
    send_intraday_qq(qiangmai_count, buy_count, update_count, prev, scan_time)
    
    print(f"  完成!")
    return update_count


if __name__ == '__main__':
    run_intraday()
