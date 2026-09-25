#!/usr/bin/env python3
"""
每日 IC 监控 — 计算模型评分与真实收益的相关性
前置检查：确保 daily 表已更新到今天

用法:
    python3 scripts/ic_daily.py
"""
import sys, json, os
from pathlib import Path
from datetime import datetime, timedelta
import sqlite3

sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))
import duckdb
from core.db import _safe_connect, checkpoint, TUSHARE_DB_PATH

DB = Path.home() / '.hermes' / 'stockdb' / 'tushare.db'
STATE_DB = Path.home() / '.hermes' / 'stockdb' / 'signals.db'  # v2温层

def check_data_ready():
    """检查数据是否已更新（找到最新的完整评分日期）"""
    today_short = datetime.now().strftime('%Y%m%d')
    
    con = _safe_connect(TUSHARE_DB_PATH, read_only=True)
    
    # 查 daily 最新日期
    latest = con.execute(
        "SELECT MAX(trade_date) FROM daily WHERE ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH'"
    ).fetchone()[0]
    con.close()
    
    if latest is None:
        return False, "daily 表为空", None
    
    latest_str = str(latest) if latest else ""
    
    # 查 signals.db 中最新的评分日期 (SQLite)
    state = sqlite3.connect(str(STATE_DB), timeout=10)
    state.execute("PRAGMA read_uncommitted = ON")
    latest_signal = state.execute(
        "SELECT date FROM signal_history ORDER BY REPLACE(date, '-', '') DESC LIMIT 1"
    ).fetchone()[0]
    state.close()
    
    if latest_signal is None:
        return False, "signal_history 表为空", None
    
    latest_signal_str = str(latest_signal)
    
    # 检查评分数
    state = sqlite3.connect(str(STATE_DB), timeout=10)
    score_count = state.execute(
        "SELECT COUNT(*) FROM signal_history WHERE date = ?", (latest_signal_str,)
    ).fetchone()[0]
    state.close()
    
    if score_count < 1000:
        return False, f"最新评分日期 {latest_signal_str} 评分数不足：{score_count}只", latest_signal_str
    
    # 检查 daily 是否已更新到该日期
    if latest_str < latest_signal_str:
        return False, f"daily 最新 {latest_str} 早于评分日期 {latest_signal_str}", latest_signal_str
    
    return True, f"评分日期 {latest_signal_str} 已就绪，评分数={score_count}", latest_signal_str

def compute_ic(signal_date_str=None, next_day=None):
    """计算 IC 指标
    
    Args:
        signal_date_str: 评分日期
        next_day: 次日日期（可选，默认自动查找下一个交易日）
    """
    if signal_date_str is None:
        signal_date_str = datetime.now().strftime('%Y%m%d')
    
    # 连接数据库
    tushare = _safe_connect(TUSHARE_DB_PATH, read_only=True)
    state = sqlite3.connect(str(STATE_DB), timeout=10)
    state.execute("PRAGMA read_uncommitted = ON")
    
    # 获取当日评分
    signals = state.execute("""
        SELECT stock_code, fusion_score, reg20, reg40, reg10, final_score
        FROM signal_history
        WHERE date = ?
    """, (signal_date_str,)).fetchall()
    state.close()  # 关闭 state 连接，避免后续写入冲突
    
    if not signals:
        return {"error": f"当日无评分数据：{signal_date_str}"}
    
    # 获取当日价格
    codes = [s[0] for s in signals]
    
    # 将 stock_code 转换为 ts_code 格式（添加.SZ 或.SH 后缀）
    def code_to_ts_code(code):
        code_str = str(code)
        if code_str.startswith(('600', '601', '602', '603', '604', '605', '688')):
            return f"{code_str}.SH"
        else:  # 000-009, 300 开头
            return f"{code_str}.SZ"
    
    ts_codes = [code_to_ts_code(code) for code in codes]
    placeholders = ','.join(['?' for _ in ts_codes])
    
    # 统一转 YYYYMMDD（daily.trade_date 格式）
    signal_ymd = signal_date_str.replace('-', '')
    
    prices = tushare.execute(f"""
        SELECT ts_code, close FROM daily 
        WHERE trade_date = ? AND ts_code IN ({placeholders})
    """, (signal_ymd,) + tuple(ts_codes)).fetchall()
    
    if not prices:
        return {"error": f"当日无价格数据：{signal_date_str}，信号数={len(signals)}"}
    
    # 获取次日价格
    if next_day is None:
        # 自动查找下一个交易日
        next_day = tushare.execute("""
            SELECT MIN(trade_date) FROM daily 
            WHERE trade_date > ? AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')
        """, (signal_ymd,)).fetchone()[0]
        
        if not next_day:
            # 今天是最新交易日，找最近有评分的交易日计算 IC
            # 从 signals.db 查最近有评分的日期（>=1000 条）
            state_check = sqlite3.connect(str(STATE_DB), timeout=10)
            recent_signal = state_check.execute("""
                SELECT date FROM signal_history 
                WHERE date < ? 
                GROUP BY date 
                HAVING COUNT(*) >= 1000 
                ORDER BY date DESC LIMIT 1
            """, (signal_date_str,)).fetchone()[0]
            state_check.close()
        
            if not recent_signal:
                return {"error": f"找不到有足够评分的历史交易日（需要>=1000 条）"}
        
            # 用这个日期的评分，以今天为次日计算 IC
            return compute_ic(recent_signal, next_day=signal_date_str)
    
    next_prices = tushare.execute(f"""
        SELECT ts_code, close FROM daily 
        WHERE trade_date = ? AND ts_code IN ({placeholders})
    """, (next_day,) + tuple(ts_codes)).fetchall()
    
    # 计算 IC
    fusion_scores = []
    reg20_scores = []
    reg40_scores = []
    reg10_scores = []
    final_scores = []
    returns = []
    price_map = {p[0]: p[1] for p in prices}
    next_map = {p[0]: p[1] for p in next_prices}
    
    for code, fusion, reg20, reg40, reg10, final in signals:
        tscode = code_to_ts_code(code)
        if tscode in price_map and tscode in next_map:
            p1 = price_map[tscode]
            p2 = next_map[tscode]
            ret = (p2 - p1) / p1 * 100  # 百分比收益
            fusion_scores.append(fusion)
            reg20_scores.append(reg20)
            reg40_scores.append(reg40)
            reg10_scores.append(reg10)
            final_scores.append(final)
            returns.append(ret)
    
    if len(fusion_scores) < 10:
        return {"error": f"样本太少：{len(fusion_scores)} 只"}
    
    # 计算各模型 Pearson 相关系数
    import numpy as np
    returns_arr = np.array(returns)
    
    def calc_ic(scores):
        # 2026-08-28 审计修复：评分零方差（std=0）时 corrcoef 出 NaN → exit 1 误报
        # （2026-08-28 实盘触发）。无区分度日返回 0.0 并标注，不告警。
        if len(scores) <= 10:
            return 0.0
        a = np.array(scores)
        if np.std(a) == 0:
            print("  ⚠️ calc_ic: 某模型当日评分零方差(无区分度), IC 记 0")
            return 0.0
        return float(np.corrcoef(a, returns_arr)[0, 1])
    
    ic_fusion = calc_ic(fusion_scores)
    ic_reg20 = calc_ic(reg20_scores)
    ic_reg40 = calc_ic(reg40_scores)
    ic_reg10 = calc_ic(reg10_scores)
    ic_final = calc_ic(final_scores)
    
    # 分组 IC (Top vs Bottom) — 用融合分排名
    df = list(zip(fusion_scores, returns))
    df.sort(key=lambda x: x[0], reverse=True)
    
    top_n = max(1, len(df) // 10)
    top_ret = sum(r for _, r in df[:top_n]) / top_n
    bottom_ret = sum(r for _, r in df[-top_n:]) / top_n
    ic_diff = top_ret - bottom_ret

    # ═══ 2026-08-05: 窗口收益预埋（fwd10/fwd20/fwd40）═══
    # 模型预测窗口是 10/20/40 交易日，次日 IC 不能验证。这里对 top10% 股票
    # 等权计算未来 10/20/40 交易日收益，数据积累满后可做真窗口 IC 对照。
    # 注：signal_date 距今不足 N 日时对应窗口收益为 NULL（等待时间推进自动填满）。
    fwd10 = fwd20 = fwd40 = None
    top_codes = [code_to_ts_code(c) for c, _ in df[:top_n]]
    fwd_map = {}  # 交易日 -> 收盘价 dict（只查需要的日期）
    def _fwd_ret(offset):
        if offset == 1:
            return None  # 次日收益已有（next_day），不做窗口
        # 目标日 = signal_ymd 之后的第 offset 个交易日
        try:
            fwd_day = tushare.execute(
                "SELECT trade_date FROM daily WHERE trade_date > ? AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH') "
                "GROUP BY trade_date ORDER BY trade_date LIMIT 1 OFFSET ?", (signal_ymd, offset - 1)).fetchone()
            if not fwd_day:
                return None
            fwd_day = str(fwd_day[0])
            # 查 top 股票的 fwd 日收盘
            ph = ','.join(['?'] * len(top_codes))
            rows = tushare.execute(
                f"SELECT ts_code, close FROM daily WHERE trade_date = ? AND ts_code IN ({ph})",
                (fwd_day,) + tuple(top_codes)).fetchall()
            pmap = {r[0]: r[1] for r in rows}
            rets = []
            for tc in top_codes:
                p0 = price_map.get(tc)
                pn = pmap.get(tc)
                if p0 and pn and p0 > 0:
                    rets.append((pn / p0 - 1) * 100)
            if len(rets) >= max(5, len(top_codes) // 2):
                return round(sum(rets) / len(rets), 3)
            return None
        except Exception:
            return None
    fwd10 = _fwd_ret(10)
    fwd20 = _fwd_ret(20)
    fwd40 = _fwd_ret(40)
    
    # 写入 signals.db (SQLite)
    conn = sqlite3.connect(str(STATE_DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    
    # 创建表（如果不存在）- 用 signal_date 做主键确保每个交易日一条
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ic_daily (
            calc_date DATE,
            signal_date DATE PRIMARY KEY,
            sample_size INTEGER,
            ic_fusion DOUBLE,
            ic_reg20 DOUBLE,
            ic_reg40 DOUBLE,
            ic_reg10 DOUBLE,
            ic_final DOUBLE,
            top_ret DOUBLE,
            bottom_ret DOUBLE,
            ic_diff DOUBLE,
            fwd10 DOUBLE,
            fwd20 DOUBLE,
            fwd40 DOUBLE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 2026-08-05: 旧表加窗口收益列（ALTER 兼容，已存在则跳过）
    for col in ('fwd10', 'fwd20', 'fwd40'):
        try:
            conn.execute(f"ALTER TABLE ic_daily ADD COLUMN {col} DOUBLE")
            print(f"  ✅ ic_daily 增加列 {col}（窗口收益预埋）")
        except Exception:
            pass  # 列已存在
    
    # 兼容旧表：早期版本无主键，重建以保证 INSERT OR REPLACE 生效
    pk_info = conn.execute("PRAGMA table_info(ic_daily)").fetchall()
    has_pk = any(row[5] for row in pk_info)
    if not has_pk:
        print("  ⚠️ ic_daily 表无主键（旧版结构），重建表...")
        conn.execute("ALTER TABLE ic_daily RENAME TO ic_daily_old")
        conn.execute("""
            CREATE TABLE ic_daily (
                calc_date DATE,
                signal_date DATE PRIMARY KEY,
                sample_size INTEGER,
                ic_fusion DOUBLE,
                ic_reg20 DOUBLE,
                ic_reg40 DOUBLE,
                ic_reg10 DOUBLE,
                ic_final DOUBLE,
                top_ret DOUBLE,
                bottom_ret DOUBLE,
                ic_diff DOUBLE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT INTO ic_daily (calc_date, signal_date, sample_size, ic_fusion, ic_reg20, ic_reg40, ic_reg10, ic_final, top_ret, bottom_ret, ic_diff, created_at)
            SELECT calc_date, signal_date, sample_size, ic_fusion, ic_reg20, ic_reg40, ic_reg10, ic_final, top_ret, bottom_ret, ic_diff, created_at
            FROM ic_daily_old
        """)
        conn.execute("DROP TABLE ic_daily_old")
        conn.commit()
        print("  ✅ ic_daily 表重建完成（signal_date 主键生效）")
    
    # 插入数据 (SQLite 用 INSERT OR REPLACE)
    conn.execute(
        "INSERT OR REPLACE INTO ic_daily "
        "(calc_date, signal_date, sample_size, ic_fusion, ic_reg20, ic_reg40, ic_reg10, ic_final, top_ret, bottom_ret, ic_diff, fwd10, fwd20, fwd40) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().date(), datetime.strptime(signal_ymd, '%Y%m%d').date(), len(fusion_scores), ic_fusion, ic_reg20, ic_reg40, ic_reg10, ic_final, top_ret, bottom_ret, ic_diff, fwd10, fwd20, fwd40))
    
    conn.commit()
    conn.close()
    
    return {
        "signal_date": signal_date_str,
        "sample_size": len(fusion_scores),
        "ic_fusion": round(ic_fusion, 4),
        "ic_reg20": round(ic_reg20, 4),
        "ic_reg40": round(ic_reg40, 4),
        "ic_reg10": round(ic_reg10, 4),
        "ic_final": round(ic_final, 4),
        "top_ret": round(top_ret, 2),
        "bottom_ret": round(bottom_ret, 2),
        "ic_diff": round(ic_diff, 2),
        "fwd10": fwd10,
        "fwd20": fwd20,
        "fwd40": fwd40,
        "status": "✅" if abs(ic_fusion) > 0.03 else "⚠️"
    }

def main():
    print(f"=== IC 监控 ===")
    print(f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查数据
    ready, msg, signal_date = check_data_ready()
    print(f"数据检查：{msg}")
    
    if not ready:
        print(f"⏸️  跳过：数据未更新完成")
        return {"status": "skipped", "reason": msg}
    
    # 计算 IC
    result = compute_ic(signal_date)
    
    if "error" in result:
        print(f"❌ 错误：{result['error']}")
    else:
        print(f"✅ 融合IC: {result['ic_fusion']:.4f} | 10d: {result['ic_reg10']:.4f} | 20d: {result['ic_reg20']:.4f} | 40d: {result['ic_reg40']:.4f}")
        print(f"   样本：{result['sample_size']}")
        print(f"   Top 10%: {result['top_ret']:+.2f}%, Bottom 10%: {result['bottom_ret']:+.2f}%")
        print(f"   IC 差值：{result['ic_diff']:.2f}%")
    
    return result

if __name__ == "__main__":
    result = main()
    print(f"\n结果：{json.dumps(result, ensure_ascii=False, indent=2)}")
