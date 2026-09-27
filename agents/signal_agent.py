#!/usr/bin/env python3
"""
信号层 — 全市场扫描评分
=========================
功能：
1. 每日盘后 15:40 运行
2. 全市场 5500+ 只股票跑因子 + 模型评分
3. 写入 signal_history 表（个股页面评分历史）
4. 输出观察名单到 signals/ 目录

输出格式:
    signals/{date}_signals.json
    [{
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "industry": "白酒",
        "date": "2026-06-23",
        "final_score": 72.5,
        "fusion_avg": 70.3,
        "reg20": 65.2,
        "reg40": 72.1,
        "reg10": 58.0,
        "lstm": 55.0,
        "cls27_prob": 0.62,
        "fusion": 68.0,
        "fusion_v9": 70.1,
        "deviation120": -0.05
    }]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import time
import statistics
from datetime import datetime
from typing import List, Dict, Optional

import duckdb
import numpy as np
import os

from core.db import TUSHARE_DB_PATH, get_db, get_tushare_db, connect_ledger, connect_signals
from core.scoring import score_stock


# ── 配置（v8单一模型）─────────────────────────────────────────

# v8阈值：基于v8的IC=0.13，用百分位排名代替绝对分数
TOP_N = 10  # 最多取前 N 只

# 排除板块
EXCLUDE_BOARDS = {'ST', '北证'}  # ST 股和北交所暂不纳入


def get_all_stocks() -> List[Dict]:
    """获取全市场股票列表（排除 ST、北交所、新股、无财务/估值数据的股票）"""
    conn = get_tushare_db(read_only=True)

    # 从 tushare.db stock_basic 获取股票列表
    rows = conn.execute("""
        SELECT symbol, name, industry, market, list_date
        FROM stock_basic
        WHERE market != '北交所'
          AND list_date IS NOT NULL
    """).fetchall()
    conn.close()

    # 收集所有有财务数据的ts_code（去重）— 用 fina_indicator
    fin_codes = set()
    val_codes = set()
    try:
        conn2 = get_tushare_db(read_only=True)
        fin_rows = conn2.execute("""
            SELECT DISTINCT ts_code FROM fina_indicator WHERE roe IS NOT NULL AND roe != ''
        """).fetchall()
        fin_codes = {r[0].replace('.SH', '').replace('.SZ', '') for r in fin_rows}

        val_rows = conn2.execute("""
            SELECT DISTINCT ts_code FROM daily_basic WHERE pe_ttm IS NOT NULL AND pe_ttm != ''
        """).fetchall()
        val_codes = {r[0].replace('.SH', '').replace('.SZ', '') for r in val_rows}
        conn2.close()
    except Exception:
        pass

    result = []
    for r in rows:
        symbol, name, industry, market, list_date = r
        code = symbol  # symbol 就是纯数字代码，如 '000001'
        # 排除 ST 股（含 *ST）和退市股（名字带"退"）
        if name and ('ST' in name or 'st' in name or '退' in name):
            continue
        # 排除北交所（8/4/92开头）
        if code.startswith(('8', '4', '92')):
            continue
        # 排除上市不足1年的新股（list_date可能是 YYYYMMDD 或 YYYY-MM-DD）
        if list_date:
            ld_str = str(list_date)
            try:
                list_dt = datetime.strptime(ld_str, '%Y-%m-%d')
            except ValueError:
                list_dt = datetime.strptime(ld_str[:8], '%Y%m%d')
            if list_dt > datetime.now().replace(year=datetime.now().year - 1):
                continue
        # 排除无财务数据的股票
        if fin_codes and code not in fin_codes:
            continue
        # 排除无估值数据的股票
        if val_codes and code not in val_codes:
            continue
        result.append({
            'stock_code': code,
            'stock_name': name or '',
            'industry': industry or '',
            'board': market or '',
            'list_date': list_date,
        })

    return result


def scan_stock(code_info: Dict, target_date: str = None, conn=None) -> Optional[Dict]:
    """扫描单只股票，返回评分结果"""
    code = code_info['stock_code']
    # 修复(0926): 北交所(9开头)在 tushare 表中后缀是 .BJ，旧写法映射到 .SH
    if code.startswith('9'):
        ts_code = f"{code}.BJ"
    elif code.startswith(('6', '68')):
        ts_code = f"{code}.SH"
    else:
        ts_code = f"{code}.SZ"
    own_conn = conn is None
    if own_conn:
        import duckdb
        from core.db import TUSHARE_DB_PATH
        conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)

    if target_date:
        # target_date 此时已是 YYYYMMDD（run_scan 入口统一转换过）
        rows = conn.execute(f"""
            SELECT d.trade_date, d.close, d.open, d.high, d.low, d.pct_chg as change_pct, d.vol as volume, d.amount, a.adj_factor
            FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
            WHERE d.ts_code = '{ts_code}' AND d.trade_date <= '{target_date}'
            ORDER BY d.trade_date DESC LIMIT 200
        """).fetchall()
    else:
        rows = conn.execute(f"""
            SELECT d.trade_date, d.close, d.open, d.high, d.low, d.pct_chg as change_pct, d.vol as volume, d.amount, a.adj_factor
            FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
            WHERE d.ts_code = '{ts_code}'
            ORDER BY d.trade_date DESC LIMIT 200
        """).fetchall()

    if not rows or len(rows) < 120:
        conn.close()
        return None

    scores = score_stock(code, rows, conn=conn, as_of_date=target_date)
    if own_conn:
        conn.close()

    if scores is None:
        return None

    closes = [float(r[1]) for r in rows]
    closes_sorted = closes[::-1]
    dev120 = 0.0
    if len(closes_sorted) >= 120:
        dev120 = closes_sorted[-1] / closes_sorted[-120] - 1

    # --- 复权价序列（09-21 修复：CMMR 三因子此前用不复权价，除权日假超卖/假翻负红线）---
    # rows 按日期 DESC；转升序后 adj_factor ffill 前向填充，close*factor 得后复权价。
    # slope/pct_chg_10d 都是比值，因子整体归一化不影响档位。缺失日（停牌）以最近可得因子代替。
    adj_sorted = []
    _f = None
    for r in reversed(rows):
        if r[8] is not None:
            _f = float(r[8])
        adj_sorted.append(_f)
    n_f = len(adj_sorted)
    _bf = None
    for k in range(n_f - 1, -1, -1):   # 头部（最早几天）因子缺失时向后找
        if adj_sorted[k] is None:
            adj_sorted[k] = _bf if _bf is not None else 1.0
        else:
            _bf = adj_sorted[k]
    _base = adj_sorted[-1] if adj_sorted and adj_sorted[-1] else 1.0
    closes_adj = [c * (f / _base) for c, f in zip(closes_sorted, adj_sorted)]

    # 计算 MA40 和 MA40 斜率 (用于 CMMR 策略) —— 复权口径
    ma40 = None
    ma40_lag20 = None
    ma40_slope = 0.0
    if len(closes_adj) >= 40:
        ma40 = statistics.mean(closes_adj[-40:])
        if len(closes_adj) >= 60:  # 需要至少 60 天数据才能计算 20 天前的 MA40
            ma40_lag20 = statistics.mean(closes_adj[-60:-20])
            if ma40_lag20 and ma40_lag20 > 0:
                ma40_slope = (ma40 - ma40_lag20) / ma40_lag20
    
    # 布林带（MA20 ± 2σ）确定下轨和止损
    entry_low, entry_high, target_price, stop_loss = 0.0, 0.0, 0.0, 0.0
    if len(closes_sorted) >= 20:
        ma20 = statistics.mean(closes_sorted[-20:])
        std20 = statistics.stdev(closes_sorted[-20:])
        entry_low = round(ma20 - 2 * std20, 2)
        # entry_low 不能为负
        entry_low = max(0.01, entry_low)
        # 布林带上下轨确定买入区间和目标
        # entry_low  = MA20 - 2σ（布林下轨，买区底部）
        # entry_high = MA20 + 0.5σ（布林中上轨，还能买的上限）
        entry_high = round(ma20 + 0.5 * std20, 2)
        # 目标价 = MA20 + 2σ（布林上轨，超买止盈）
        target_price = round(ma20 + 2 * std20, 2)
        # 止损：布林下轨（MA20 - 2σ）作为止损参考，接近成本时更早保护
        # 注意：必须比硬止损(-12%)更早触发才有意义；用 max(布林下轨, 现价×0.88) 保底
        stop_loss = round(max(ma20 - 2 * std20, closes_sorted[-1] * 0.88), 2)
    
    # 计算 vol_ratio (量比，用于 CMMR 策略)
    vol_ratio = 1.0
    if len(rows) >= 5:
        # 当日成交量
        today_vol = float(rows[0][6]) if rows[0][6] else 0
        # 5 日均量
        avg_vol = sum(float(r[6]) for r in rows[:5] if r[6]) / 5
        if avg_vol > 0:
            vol_ratio = today_vol / avg_vol

    # 真实 10 日涨跌幅（用于 CMMR 超卖判断，而非模型预测 reg10）—— 复权口径（09-21）
    pct_chg_10d = 0.0
    if len(closes_adj) >= 11:
        pct_chg_10d = (closes_adj[-1] - closes_adj[-11]) / closes_adj[-11]

    return {
        'stock_code': code,
        'stock_name': code_info.get('stock_name', ''),
        'industry': code_info.get('industry', ''),
        'board': code_info.get('board', ''),
        'date': target_date or str(rows[0][0])[:10],
        'v8_score': scores.get('fusion', scores.get('reg20_pred', scores['reg_pred'])),  # 用融合分做百分位排名
        'final_score': 0,
        'fusion_avg': 0,
        'reg20': scores.get('reg20_pred', scores['reg_pred']),  # 修(0927): 显式接20d预测;旧版接reg_pred在20d维度失败时落0
        'reg40': scores.get('reg40_pred', 0),
        'reg10': scores.get('reg10_pred', 0),  # 修复：用实际值
        'lstm': 50,
        'cls27_prob': 0.5,
        'fusion': scores.get('fusion', 0),
        'fusion_v9': scores.get('fusion_v9', 0),
        'reg_pred': scores['reg_pred'],
        'reg10_pred': scores.get('reg10_pred'),  # 修复：用实际值
        'reg40_pred': scores.get('reg40_pred'),
        'deviation120': round(dev120, 4),
        'entry_low': entry_low, 'entry_high': entry_high,
        'target_price': target_price, 'stop_loss': stop_loss,
        # CMMR 所需字段
        'ma40': ma40,
        'ma40_lag20': ma40_lag20,
        'ma40_slope': ma40_slope,
        'vol_ratio': vol_ratio,
        'pct_chg_10d': pct_chg_10d,
        'close': closes_sorted[-1] if closes_sorted else 0,
        'open': float(rows[0][2]) if rows and rows[0][2] else 0,
    }


def save_signals_all(all_scored: List[Dict], watchlist: List[Dict], target_date: str):
    """
    保存信号：所有评分写入 signals.db.signal_history（v2温层），观察名单写入 ledger.db.watchlist（v2热层）
    """
    BASE = Path.home() / '.hermes' / 'stockdb'
    STATE_DB_PATH = BASE / 'signals.db'   # v2温层: signal_history
    LEDGER_DB_PATH = BASE / 'ledger.db'   # v2热层: watchlist
    sig_dir = BASE / 'signals'
    sig_dir.mkdir(exist_ok=True)

    date_str = target_date.replace('-', '')

    # 1. （已删除：signals/{date}_signals.json 冗余写入——只有死代码 risk_agent 读，
    #    数据全量在 signals.db.signal_history（v2温层），JSON 文件无人消费）
    # 2. 写入 signals.db/ledger.db (SQLite, v2三层)
    try:
        import sqlite3
        state_conn = connect_signals()  # 统一入口(v2温层)
        state_conn.execute("PRAGMA journal_mode=WAL")
        state_conn.execute("PRAGMA busy_timeout=30000")
        
        # 写入全量评分到 signal_history (v2温层 signals.db)
        # 新增 cmmr_score, fusion_score, ma40_slope 列
        state_conn.execute("""CREATE TABLE IF NOT EXISTS signal_history (
            date DATE, stock_code VARCHAR, stock_name VARCHAR, industry VARCHAR, 
            fusion_score DOUBLE, reg20 DOUBLE, reg40 DOUBLE, reg10 DOUBLE, 
            gtja_score DOUBLE, deviation120 DOUBLE, final_score DOUBLE, 
            fusion_avg DOUBLE, cls27_prob DOUBLE, lstm DOUBLE, 
            reg_pred DOUBLE, reg10_pred DOUBLE, reg40_pred DOUBLE,
            old_score DOUBLE, cmmr_score DOUBLE, fusion_score_cmmr DOUBLE, ma40_slope DOUBLE
        )""")
        
        # 用 REPLACE 统一日期格式，避免 20260727 vs 2026-07-27 的重复
        state_conn.execute(f"DELETE FROM signal_history WHERE REPLACE(date, '-', '') = '{date_str}'")
        for s in all_scored:
            state_conn.execute("""
                INSERT OR REPLACE INTO signal_history
                (date, stock_code, stock_name, industry, fusion_score, reg20, reg40, reg10, gtja_score, deviation120, final_score, fusion_avg, cls27_prob, lstm, reg_pred, reg10_pred, reg40_pred, old_score, cmmr_score, fusion_score_cmmr, ma40_slope)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                s['date'], s['stock_code'], s['stock_name'], s['industry'],
                s.get('fusion', 0), s['reg20'], s['reg40'], s['reg10'],
                0, s.get('deviation120', 0), s['final_score'], s['fusion_avg'], 
                s.get('cls27_prob', 0), s.get('lstm', 0), s.get('reg_pred', 0), 
                s.get('reg10_pred'), s.get('reg40_pred'),
                s.get('old_score', 0), s.get('cmmr_score', 0), s.get('fusion_score', 0), s.get('ma40_slope', 0),
            ))
        
        # 3. 写入观察名单到 ledger.db.watchlist (先清后写，避免脏数据)
        # scan_date 统一存 YYYYMMDD（与 signal_history.date 一致），避免混格式导致清理失效
        wl_conn = connect_ledger()  # 统一入口(v2热层)
        wl_conn.execute("PRAGMA journal_mode=WAL")
        wl_conn.execute("PRAGMA busy_timeout=30000")
        wl_conn.execute(f"DELETE FROM watchlist WHERE REPLACE(scan_date, '-', '') = '{date_str}'")
        for w in watchlist:
            wl_conn.execute("INSERT OR REPLACE INTO watchlist (ts_code, score, scan_date, status, entry_low, entry_high, target_price, stop_loss) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                               (w['stock_code'], w['final_score'], date_str, 'pending',
                                w.get('entry_low', 0), w.get('entry_high', 0),
                                w.get('target_price', 0), w.get('stop_loss', 0)))
        
        # 清理旧数据：保留最近 20 个交易日的观察名单
        wl_conn.execute("""
            DELETE FROM watchlist 
            WHERE scan_date NOT IN (
                SELECT DISTINCT scan_date FROM watchlist 
                WHERE scan_date IS NOT NULL 
                ORDER BY scan_date DESC LIMIT 20
            )
        """)
        wl_conn.commit()
        wl_conn.close()
        
        state_conn.commit()
        state_conn.close()
        print(f"  写入成功：历史(signals.db) {len(all_scored)} 条，观察名单(ledger.db) {len(watchlist)} 条")
    except Exception as e:
        print(f"  [ERROR] 写入失败：{e}")
        try: state_conn.close()
        except Exception: pass
    print(f"  写入 signal_history 表: {len(all_scored)} 条（全部评分）")


def run_scan(target_date: str = None) -> List[Dict]:
    """
    全市场扫描入口
    """
    # 统一日期为主库格式 YYYYMMDD
    if target_date:
        target_date = target_date.replace('-', '')
    else:
        target_date = datetime.now().strftime('%Y%m%d')

    print("=" * 50)
    print(f"信号层扫描开始: {target_date}")
    print("=" * 50)

    start_time = time.time()

    # 1. 获取股票列表
    stocks = get_all_stocks()
    print(f"股票总数: {len(stocks)}")

    # 2. 全市场扫描（开一次 DuckDB 连接复用所有股票，避免锁开销）
    import duckdb
    from core.db import TUSHARE_DB_PATH
    scan_conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
    results = []
    skipped = 0
    errors = 0

    for i, s in enumerate(stocks):
        try:
            result = scan_stock(s, target_date, conn=scan_conn)
            if result:
                results.append(result)
            else:
                skipped += 1
        except Exception as e:
            errors += 1

        if (i + 1) % 500 == 0:
            elapsed = time.time() - start_time
            print(f"  进度: {i+1}/{len(stocks)} | "
                  f"已评分: {len(results)} | "
                  f"跳过: {skipped} | "
                  f"错误: {errors} | "
                  f"耗时: {elapsed:.0f}s")

    elapsed = time.time() - start_time
    print(f"\n扫描完成:")
    print(f"  已评分: {len(results)} 只")
    print(f"  跳过: {skipped} 只（数据不足）")
    print(f"  错误: {errors} 只")
    print(f"  耗时: {elapsed:.0f}s ({elapsed/len(stocks):.3f}s/股)")

    scan_conn.close()

    if not results:
        print("没有评分结果，退出")
        return []

    # 3. v8 单一模型：用百分位排名生成 0-100 分
    # v8 输出是 20 日预期收益率（百分数），直接做横截面百分位排名
    
    all_v8_scores = np.array([r['v8_score'] for r in results])
    
    # 计算每个值的百分位排名（越高越好）
    sorted_indices = np.argsort(all_v8_scores)  # 升序排序的索引
    ranks = np.empty(len(sorted_indices), dtype=float)
    ranks[sorted_indices] = np.arange(1, len(all_v8_scores) + 1)  # 每个值的排名（从 1 开始）
    
    pctiles = (ranks / len(ranks)) * 100  # 百分位：0-100
    
    for i, r in enumerate(results):
        r['old_score'] = round(float(pctiles[i]), 1)  # 原三因子分（用于 CMMR 融合）
        r['final_score'] = r['old_score']  # 默认使用原分
        r['fusion_avg'] = r['old_score']  # v8 单一模型
    
    # --- CMMR 双轨策略集成 (新增两套独立评分) ---
    from scripts.cmmr_standalone import calculate_cmmr_score
    from scripts.cmmr_trifactor_fusion import calculate_trifactor_cmmr_fusion
    
    # 将 results 转为 DataFrame 以便调用 CMMR 模块
    import pandas as pd
    df = pd.DataFrame(results)
    
    # 计算新增评分
    df = calculate_cmmr_score(df)  # 新增 'cmmr_score'
    df = calculate_trifactor_cmmr_fusion(df)  # 新增 'fusion_score'
    
    # 将 DataFrame 转回 list of dict
    results = df.to_dict('records')
    
    # 【配置开关】：选择使用哪个评分进行最终排序
    # MODE = 'original'   # 使用原三因子 (old_score) - 默认
    # MODE = 'cmmr'       # 使用 CMMR 独立 (cmmr_score)
    # MODE = 'fusion'     # 使用 CMMR+ 模型融合 (fusion_score；原名"三因子融合"系误称，2026-08-10 更正)
    # MODE = 'compare'    # 同时输出三套排名（推荐，用于对比）
    MODE = 'original'  # 默认使用原策略，确认无误后再切换
    
    # 输出对比 (仅在 compare 模式)
    if MODE == 'compare':
        print("\n=== 三套评分对比 (Top 5) ===")
        print("\n【原三因子】:")
        sorted_old = sorted(results, key=lambda x: x['old_score'], reverse=True)
        for r in sorted_old[:5]:
            print(f"  {r['stock_code']} {r['stock_name']} old_score={r['old_score']:.1f} reg10={r['reg10']:.3f}")
        
        print("\n【CMMR 独立】:")
        sorted_cmmr = sorted(results, key=lambda x: x['cmmr_score'], reverse=True)
        for r in sorted_cmmr[:5]:
            print(f"  {r['stock_code']} {r['stock_name']} cmmr_score={r['cmmr_score']:.1f} ma40_slope={r['ma40_slope']:.4f}")
        
        print("\n【CMMR+ 模型融合】:")
        sorted_fusion = sorted(results, key=lambda x: x['fusion_score'], reverse=True)
        for r in sorted_fusion[:5]:
            print(f"  {r['stock_code']} {r['stock_name']} fusion_score={r['fusion_score']:.1f} old_score={r['old_score']:.1f} ma40_slope={r['ma40_slope']:.4f}")
        
        # 对比模式下，默认使用融合评分排序
        results.sort(key=lambda x: x['fusion_score'], reverse=True)
        for r in results:
            r['final_score'] = r['fusion_score']
    
    elif MODE == 'original':
        results.sort(key=lambda x: x['old_score'], reverse=True)
        for r in results:
            r['final_score'] = r['old_score']
    
    elif MODE == 'cmmr':
        results.sort(key=lambda x: x['cmmr_score'], reverse=True)
        for r in results:
            r['final_score'] = r['cmmr_score']
    
    elif MODE == 'fusion':
        results.sort(key=lambda x: x['fusion_score'], reverse=True)
        for r in results:
            r['final_score'] = r['fusion_score']
    
    # 3.5 过滤：entry_low ≤ 0.01（布林下轨无效，极端波动股）视为异常
    results = [r for r in results if r.get('entry_low', 0) > 0.01]
    
    watchlist = results[:TOP_N]

    print(f"\n观察名单: {len(watchlist)} 只（前TOP={TOP_N}）")
    if watchlist:
        print(f"  Top 10:")
        for r in watchlist[:10]:
            print(f"    {r['stock_code']} {r['stock_name']} "
                  f"score={r['final_score']} "
                  f"reg20={r['reg20']} reg40={r['reg40']} reg10={r['reg10']}")

    # 4. 保存（所有评分写入历史 + 观察名单保存 JSON）
    date_str = target_date or datetime.now().strftime('%Y%m%d')
    save_signals_all(results, watchlist, date_str)

    return watchlist


def format_report(watchlist, date_str):
    """格式化成 QQ 推送消息"""
    if not watchlist:
        return "今日无信号。"

    lines = [f"📊 {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 盘后选股报告"]
    lines.append(f"⚡ TOP {len(watchlist)} 只观察名单:")
    lines.append("")

    for i, r in enumerate(watchlist[:10], 1):
        code = r['stock_code']
        name = r.get('stock_name', '')
        score = r.get('final_score', 0)
        reg10 = r.get('reg10', 0)
        reg20 = r.get('reg20', 0)
        reg40 = r.get('reg40', 0)
        ind = r.get('industry', '?')
        dev120 = r.get('deviation120', 0)

        lines.append(
            f"  {i:2d}. [{score:>5.0f}] {code} {name:<8} "
            f"| {ind} | 10d={reg10:+.2f} 20d={reg20:.1f} 40d={reg40:.1f} dev120={dev120:+.1%}"
        )

    lines.append("")
    lines.append("📌 分数=百分位排名(越高越好) | 仅供参考，注意风险")

    return '\n'.join(lines)


def send_qq_report(watchlist, date_str):
    """通过 hermes send 发QQ消息"""
    msg = format_report(watchlist, date_str)

    # 方案1：直接调用 hermes CLI 发 QQ
    try:
        import subprocess
        result = subprocess.run(
            ['hermes', 'send', '-t', 'qqbot', msg],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"  ✅ QQ报告已发送")
            return True
    except Exception as e:
        pass

    # 方案2：写 qq_pending.txt，让 cron job 兜底转发
    try:
        pending = Path.home() / '.hermes' / 'stockdb' / 'scripts' / 'daban' / 'qq_pending.txt'
        with open(pending, 'a') as f:
            f.write(msg + '\n')
        print(f"  📝 QQ报告已写入 {pending}")
    except Exception as e:
        pass

    # 方案3：打印到终端（cron job会捕获输出）
    print(f"\n{msg}")
    return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='全市场扫描评分')
    parser.add_argument('--date', type=str, default=None,
                        help='目标日期 YYYYMMDD（默认最新交易日）')
    args = parser.parse_args()

    # 2026-08-10 前置检查：daily 数据新鲜度——数据更新失败时禁止用旧行情写错误信号
    # （08-10 事故：16:00 数据更新超时，17:45 扫描用 8/7 数据算出"8/10 信号"，与 8/7 几乎相同
    #   被健康检查复制检测捕获。宁可扫描失败告警，不写脏信号。）
    try:
        import duckdb as _dk
        from core.db import TUSHARE_DB_PATH as _TDB
        _tconn = _dk.connect(str(_TDB), read_only=True)
        _daily_max = _tconn.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
        _tconn.close()
        _target = args.date or datetime.now().strftime('%Y%m%d')
        if _daily_max and _daily_max < _target:
            print(f"❌ 数据新鲜度检查失败：daily 最新={_daily_max} < 目标={_target}")
            print("   数据更新可能失败。请先修复数据更新（bash update_data.sh），再重跑扫描。")
            sys.exit(1)
    except Exception as _fe:
        print(f"⚠️ 数据新鲜度检查异常（{_fe}），继续扫描", flush=True)

    signals = run_scan(args.date)
    print(f"\n✅ 扫描完成，观察名单 {len(signals)} 只")

    if signals:
        date_str = args.date or datetime.now().strftime('%Y%m%d')
                # 2026-09-09 用户拍板：取消 signal_agent 单独 QQ 推送
        # 原因：盘后报告(23:00)已包含 Top10 观察名单，不重复打扰
        # 只停推送，扫描入库照常（signal_history 是盘后报告数据源）
        # send_qq_report(signals, date_str)
        print(f"  QQ 单独推送已停用（2026-09-09 用户决定，Top10 见每日盘后报告）")
