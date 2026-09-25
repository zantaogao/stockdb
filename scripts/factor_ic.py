#!/usr/bin/env python3
"""特征分组 IC 计算 — 监控模型各维度的预测力"""
import sys, json, sqlite3, numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import get_tushare_db, get_state_db

BASE = Path(__file__).resolve().parent.parent
STATE_DB = BASE / 'signals.db'  # v2温层

# 模型特征分组 → 可计算因子
FACTOR_GROUPS = {
    '短期动量': {
        'fields': ['chg5', 'chg10'],
        'sql': lambda code, dt: None,  # 特殊处理
        'desc': '5日/10日涨幅',
    },
    '中期动量': {
        'fields': ['chg20', 'chg60', 'chg120'],
        'desc': '20日/60日/120日涨幅',
    },
    '量能': {
        'fields': ['turnover_rate', 'volume_ratio'],
        'desc': '换手率/量比',
    },
    '波动': {
        'fields': ['std20', 'atr_bfq'],
        'desc': '20日波动率/真实波幅',
    },
    '估值': {
        'fields': ['pe_ttm', 'pb'],
        'desc': 'PE/PB',
    },
    '技术指标': {
        'fields': ['macd_dif', 'kdj_k', 'rsi_12', 'cci'],
        'desc': 'MACD/KDJ/RSI/CCI',
    },
    '形态': {
        'fields': ['skew20', 'dn_streak', 'up_ratio10'],
        'desc': '偏度/连跌天数/上涨比例',
    },
    '情绪': {
        'fields': ['mfi_bfq', 'psy_bfq', 'wr_bfq'],
        'desc': '资金流/心理线/威廉指标',
    },
    # 三因子体系（2026-08-02 新增）：数据源在 signals.db 的 new_factors/flow_alpha/vol_adj 表（历史在 factors.db）
    '三因子_ma_decay': {
        'fields': ['ma_decay'],
        'desc': '均值回归衰减（三因子）',
        'source': 'state.new_factors',
    },
    '三因子_flow_alpha': {
        'fields': ['flow_alpha'],
        'desc': '资金流（三因子）',
        'source': 'state.flow_alpha',
    },
    '三因子_vol_adj': {
        'fields': ['vol_adj'],
        'desc': '波动调整（三因子，低=好）',
        'source': 'state.vol_adj',
    },
}

def safe_float(v):
    try:
        return float(v) if v is not None and v != '' else None
    except:
        return None

def safe_avg(arr):
    valid = [x for x in arr if x is not None and not np.isnan(x) and not np.isinf(x)]
    return np.mean(valid) if valid else None

def group_value_from_extra(ts_code, trade_date, group_name, extra_data):
    """从 stk_factor 的 extra 字段提取因子组的值"""
    if not extra_data:
        return {}
    
    result = {}
    
    if group_name == '量能':
        result['turnover_rate'] = safe_float(extra_data.get('turnover_rate'))
        result['volume_ratio'] = safe_float(extra_data.get('volume_ratio'))
    
    elif group_name == '估值':
        result['pe_ttm'] = safe_float(extra_data.get('pe_ttm'))
        result['pb'] = safe_float(extra_data.get('pb'))
    
    elif group_name == '技术指标':
        result['macd_dif'] = safe_float(extra_data.get('macd_dif_bfq'))
        result['kdj_k'] = safe_float(extra_data.get('kdj_k_bfq'))
        result['rsi_12'] = safe_float(extra_data.get('rsi_bfq_12'))
        result['cci'] = safe_float(extra_data.get('cci_bfq'))
    
    elif group_name == '波动':
        result['atr_bfq'] = safe_float(extra_data.get('atr_bfq'))
    
    elif group_name == '情绪':
        result['mfi_bfq'] = safe_float(extra_data.get('mfi_bfq'))
        result['psy_bfq'] = safe_float(extra_data.get('psy_bfq'))
        result['wr_bfq'] = safe_float(extra_data.get('wr_bfq'))
    
    return result

def compute_group_ics(signal_date_str):
    """计算各特征分组的IC"""
    tushare = get_tushare_db()
    
    # 获取所有A股 → ts_code
    raw_stocks = [r[0] for r in tushare.execute("""
        SELECT symbol FROM stock_basic 
        WHERE market != '北交所' AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%'
        AND (name NOT LIKE '%ST%' OR name IS NULL)
    """).fetchall()]
    
    codes = []
    ts_code_map = {}
    for s in raw_stocks:
        tscode = f"{s}.SH" if s.startswith(('6','68','9')) else f"{s}.SZ"
        codes.append(tscode)
        ts_code_map[tscode] = s
    placeholders = ','.join(['?' for _ in codes])
    
    # 当日价格
    prices = tushare.execute(f"""
        SELECT ts_code, close FROM daily 
        WHERE trade_date = ? AND ts_code IN ({placeholders})
    """, (signal_date_str,) + tuple(codes)).fetchall()
    
    if not prices:
        latest = tushare.execute("SELECT MAX(trade_date) FROM daily").fetchone()
        if latest and latest[0]:
            signal_date_str = str(latest[0])
            prices = tushare.execute(f"""
                SELECT ts_code, close FROM daily 
                WHERE trade_date = ? AND ts_code IN ({placeholders})
            """, (signal_date_str,) + tuple(codes)).fetchall()
    
    price_map = {r[0]: float(r[1]) for r in prices}
    
    # 次日价格
    next_day = tushare.execute("SELECT MIN(trade_date) FROM daily WHERE trade_date > ?", (signal_date_str,)).fetchone()
    if not next_day or not next_day[0]:
        return {"error": f"无次日数据：{signal_date_str}"}
    next_date = str(next_day[0])
    
    next_prices = tushare.execute(f"""
        SELECT ts_code, close FROM daily 
        WHERE trade_date = ? AND ts_code IN ({placeholders})
    """, (next_date,) + tuple(codes)).fetchall()
    next_map = {r[0]: float(r[1]) for r in next_prices}
    
    # 获取 stk_factor extra 数据（使用最新可用日期）
    factor_max_date = tushare.execute("SELECT MAX(trade_date) FROM stk_factor WHERE trade_date <= ?", 
                                       (signal_date_str,)).fetchone()
    factor_date = str(factor_max_date[0]) if factor_max_date and factor_max_date[0] else signal_date_str
    factor_rows = tushare.execute(f"""
        SELECT ts_code, extra FROM stk_factor 
        WHERE trade_date = ? AND ts_code IN ({placeholders})
    """, (factor_date,) + tuple(codes)).fetchall()
    
    extra_map = {}
    for r in factor_rows:
        try:
            extra_map[r[0]] = json.loads(r[1]) if isinstance(r[1], str) else {}
        except:
            extra_map[r[0]] = {}
    
    # 三因子数据（signals.db 的 new_factors/flow_alpha/vol_adj，按 date+裸代码）
    # 注意：signals.db 三因子表 date 是 YYYY-MM-DD 格式，signal_date_str 是 YYYYMMDD
    state_date = f"{signal_date_str[:4]}-{signal_date_str[4:6]}-{signal_date_str[6:]}"
    tri_map = {}  # (date, 裸代码) -> (ma_decay, flow_alpha, vol_adj)
    try:
        sconn = sqlite3.connect(str(STATE_DB), timeout=10)
        tri_rows = sconn.execute("""
            SELECT nf.stock_code, nf.ma_decay, fa.flow_alpha, va.vol_adj
            FROM new_factors nf
            LEFT JOIN flow_alpha fa ON nf.stock_code = fa.stock_code AND nf.date = fa.date
            LEFT JOIN vol_adj va ON nf.stock_code = va.stock_code AND nf.date = va.date
            WHERE nf.date = ?
        """, (state_date,)).fetchall()
        sconn.close()
        for r in tri_rows:
            tri_map[r[0]] = (safe_float(r[1]), safe_float(r[2]), safe_float(r[3]))
        print(f"  三因子数据: {len(tri_map)} 只 ({state_date})")
    except Exception as e:
        print(f"  三因子数据读取失败: {e}")
    
    # 计算每个分组在各个ts_code上的值
    group_results = {}
    for gname, ginfo in FACTOR_GROUPS.items():
        group_results[gname] = {'scores': [], 'returns': [], 'field_values': {}}
        for f in ginfo['fields']:
            group_results[gname]['field_values'][f] = []
    
    for tscode in codes:
        code = ts_code_map[tscode]
        
        if tscode not in price_map or tscode not in next_map:
            continue
        
        p1 = price_map[tscode]
        p2 = next_map[tscode]
        ret = (p2 - p1) / p1 * 100
        
        extra = extra_map.get(tscode, {})
        
        # 从daily计算简单因子（2026-08-03 修复未来泄漏：必须按 signal_date 截止，
        # 原查询取最新120天无过滤 → 动量/波动/形态因子混入信号日之后的收盘价，
        # 且 closes[-1] 与次日收益 ret 共用同一价格导致 IC 虚高——正常每日跑也泄漏1天）
        daily_data = tushare.execute(f"""
            SELECT trade_date, close, pct_chg, vol FROM daily 
            WHERE ts_code = ? AND trade_date <= ? ORDER BY trade_date DESC LIMIT 120
        """, (tscode, signal_date_str)).fetchall()
        
        if len(daily_data) < 20:
            continue
        
        closes = [float(r[1]) for r in daily_data][::-1]
        pcts = [float(r[2] or 0) for r in daily_data][::-1]
        vols = [float(r[3] or 0) for r in daily_data][::-1]
        
        # 计算动量
        chg5 = (closes[-1] / closes[-5] - 1) * 100 if len(closes) >= 5 else None
        chg10 = (closes[-1] / closes[-10] - 1) * 100 if len(closes) >= 10 else None
        chg20 = (closes[-1] / closes[-20] - 1) * 100 if len(closes) >= 20 else None
        chg60 = (closes[-1] / closes[-60] - 1) * 100 if len(closes) >= 60 else None
        chg120 = (closes[-1] / closes[-120] - 1) * 100 if len(closes) >= 120 else None
        
        # 波动率
        std20 = np.std(pcts[-20:]) if len(pcts) >= 20 else None
        
        # 偏度
        skew20 = float(np.mean(((np.array(pcts[-20:]) - np.mean(pcts[-20:])) / max(np.std(pcts[-20:]), 0.01)) ** 3)) if len(pcts) >= 20 else None
        
        # 连跌天数
        dn_streak = 0
        for p in reversed(pcts):
            if p < 0:
                dn_streak += 1
            else:
                break
        
        # 上涨比例
        up_ratio10 = sum(1 for p in pcts[-10:] if p > 0) / 10.0 if len(pcts) >= 10 else None
        
        extra_vals = group_value_from_extra(tscode, signal_date_str, None, extra)
        
        # 为每个分组收集
        # 短期动量
        group_results['短期动量']['field_values']['chg5'].append(chg5)
        group_results['短期动量']['field_values']['chg10'].append(chg10)
        if chg5 is not None and chg10 is not None:
            group_results['短期动量']['scores'].append((chg5 + chg10) / 2)
            group_results['短期动量']['returns'].append(ret)
        
        # 中期动量
        for fname, val in [('chg20', chg20), ('chg60', chg60), ('chg120', chg120)]:
            group_results['中期动量']['field_values'][fname].append(val)
        vals = [x for x in [chg20, chg60] if x is not None]
        if vals:
            group_results['中期动量']['scores'].append(np.mean(vals))
            group_results['中期动量']['returns'].append(ret)
        
        # 波动
        group_results['波动']['field_values']['std20'].append(std20)
        atr = safe_float(extra.get('atr_bfq'))
        group_results['波动']['field_values']['atr_bfq'].append(atr)
        v_std = std20 if std20 is not None else 0
        v_atr = atr if atr is not None else 0
        group_results['波动']['scores'].append((v_std + v_atr) / 2 if (std20 is not None or atr is not None) else None)
        if group_results['波动']['scores'][-1] is not None:
            group_results['波动']['returns'].append(ret)
        else:
            group_results['波动']['scores'].pop()
        
        # 量能
        tr = safe_float(extra.get('turnover_rate'))
        vr = safe_float(extra.get('volume_ratio'))
        group_results['量能']['field_values']['turnover_rate'].append(tr)
        group_results['量能']['field_values']['volume_ratio'].append(vr)
        v = tr if tr is not None else (vr or 0)
        group_results['量能']['scores'].append(v)
        group_results['量能']['returns'].append(ret)
        
        # 估值
        pe = safe_float(extra.get('pe_ttm'))
        pb_val = safe_float(extra.get('pb'))
        group_results['估值']['field_values']['pe_ttm'].append(pe)
        group_results['估值']['field_values']['pb'].append(pb_val)
        if pe and pe > 0:
            group_results['估值']['scores'].append(1.0 / pe)
            group_results['估值']['returns'].append(ret)
        
        # 技术指标
        md = safe_float(extra.get('macd_dif_bfq'))
        kk = safe_float(extra.get('kdj_k_bfq'))
        rs12 = safe_float(extra.get('rsi_bfq_12'))
        cc = safe_float(extra.get('cci_bfq'))
        group_results['技术指标']['field_values']['macd_dif'].append(md)
        group_results['技术指标']['field_values']['kdj_k'].append(kk)
        group_results['技术指标']['field_values']['rsi_12'].append(rs12)
        group_results['技术指标']['field_values']['cci'].append(cc)
        vals = [x for x in [md, kk, rs12, cc] if x is not None]
        if vals:
            group_results['技术指标']['scores'].append(np.mean(vals))
            group_results['技术指标']['returns'].append(ret)
        
        # 形态
        group_results['形态']['field_values']['skew20'].append(skew20)
        group_results['形态']['field_values']['dn_streak'].append(dn_streak)
        group_results['形态']['field_values']['up_ratio10'].append(up_ratio10)
        group_results['形态']['scores'].append(up_ratio10 if up_ratio10 is not None else 0.5)
        group_results['形态']['returns'].append(ret)
        
        # 情绪
        mfi = safe_float(extra.get('mfi_bfq'))
        psy = safe_float(extra.get('psy_bfq'))
        wr = safe_float(extra.get('wr_bfq'))
        group_results['情绪']['field_values']['mfi_bfq'].append(mfi)
        group_results['情绪']['field_values']['psy_bfq'].append(psy)
        group_results['情绪']['field_values']['wr_bfq'].append(wr)
        vals = [x for x in [mfi, psy] if x is not None]
        if vals:
            group_results['情绪']['scores'].append(np.mean(vals))
            group_results['情绪']['returns'].append(ret)
        
        # 三因子体系（signals.db）：ma_decay / flow_alpha / vol_adj
        tri = tri_map.get(code)
        if tri:
            md_v, fa_v, va_v = tri
            # 三因子_ma_decay
            group_results['三因子_ma_decay']['field_values']['ma_decay'].append(md_v)
            if md_v is not None:
                group_results['三因子_ma_decay']['scores'].append(md_v)
                group_results['三因子_ma_decay']['returns'].append(ret)
            # 三因子_flow_alpha
            group_results['三因子_flow_alpha']['field_values']['flow_alpha'].append(fa_v)
            if fa_v is not None:
                group_results['三因子_flow_alpha']['scores'].append(fa_v)
                group_results['三因子_flow_alpha']['returns'].append(ret)
            # 三因子_vol_adj
            group_results['三因子_vol_adj']['field_values']['vol_adj'].append(va_v)
            if va_v is not None:
                group_results['三因子_vol_adj']['scores'].append(va_v)
                group_results['三因子_vol_adj']['returns'].append(ret)
    
    # 计算每个分组的 IC
    ic_results = {}
    for gname in FACTOR_GROUPS:
        scores = np.array(group_results[gname]['scores'])
        returns_arr = np.array(group_results[gname]['returns'])
        n = len(scores)
        
        if n < 30:
            ic_results[gname] = {'ic': None, 'n': n, 'error': '样本不足'}
            continue
        
        ic = float(np.corrcoef(scores, returns_arr)[0, 1])
        ic_results[gname] = {
            'ic': round(ic, 4),
            'n': n,
            'fields': FACTOR_GROUPS[gname]['fields'],
        }
    
    return ic_results, signal_date_str

def save_results(ic_results, signal_date_str):
    """写入 signals.db"""
    conn = sqlite3.connect(str(STATE_DB), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS factor_group_ic_daily (
            calc_date TEXT, factor_name TEXT, ic REAL, 
            sample_size INTEGER, field_list TEXT,
            PRIMARY KEY (calc_date, factor_name)
        )
    """)
    
    # calc_date 用信号日（signal_date_str），保证补算历史时滚动窗口按信号日排序、不污染
    calc_date = signal_date_str.replace('-', '')
    
    for gname, ginfo in ic_results.items():
        ic_val = ginfo.get('ic')
        if ic_val is not None:
            conn.execute("""
                INSERT OR REPLACE INTO factor_group_ic_daily 
                (calc_date, factor_name, ic, sample_size, field_list)
                VALUES (?, ?, ?, ?, ?)
            """, (calc_date, gname, ic_val, ginfo['n'], ','.join(ginfo.get('fields', []))))
    
    # 同时更新滚动表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS factor_ic_roll (
            factor_name TEXT, as_of_date TEXT, window INTEGER,
            mean_ic REAL, std_ic REAL, icir REAL, win_rate REAL,
            n_days INTEGER, group_name TEXT,
            PRIMARY KEY (factor_name, as_of_date, window)
        )
    """)
    
    for gname in FACTOR_GROUPS:
        # 20日滚动均值（as_of 截止过滤：滚动窗口只用 ≤calc_date 的数据，
        # 防历史行包含未来 IC——2026-08-03 修复：原查询无日期过滤，补算后历史行混入未来数据）
        rows = conn.execute("""
            SELECT ic FROM factor_group_ic_daily 
            WHERE factor_name = ? AND calc_date <= ? ORDER BY calc_date DESC LIMIT 20
        """, (gname, calc_date)).fetchall()
        ics = [r[0] for r in rows if r[0] is not None]
        if len(ics) >= 1:
            mean_ic = np.mean(ics)
            std_ic = np.std(ics, ddof=1) if len(ics) > 1 else 0
            icir = mean_ic / std_ic if std_ic > 0 else 0
            win_rate = sum(1 for ic in ics if ic > 0) / len(ics)
            conn.execute("""
                INSERT OR REPLACE INTO factor_ic_roll 
                (factor_name, as_of_date, window, mean_ic, std_ic, icir, win_rate, n_days, group_name)
                VALUES (?, ?, 20, ?, ?, ?, ?, ?, ?)
            """, (gname, calc_date, round(mean_ic, 4), round(std_ic, 4), 
                  round(icir, 4), round(win_rate, 4), len(ics), gname))
    
    conn.commit()
    conn.close()

def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description='特征分组IC计算')
    parser.add_argument('--date', help='信号日期 (YYYYMMDD)')
    args = parser.parse_args()
    
    signal_date = args.date or datetime.now().strftime('%Y%m%d')
    max_d = None
    
    # 自动回退到有次日数据的交易日期（仅当未显式传 --date 时；显式传 --date 表示补算历史，
    # 不能被回退逻辑覆盖——2026-08-03 修复：原逻辑无条件覆盖导致 --date 参数失效）
    if not args.date:
        temp_conn = get_tushare_db()
        max_date = temp_conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()
        if max_date and max_date[0]:
            max_d = str(max_date[0])
            # 取 max_date 前一个交易日作为信号日期
            prev = temp_conn.execute("""
                SELECT MAX(trade_date) FROM daily WHERE trade_date < ?
            """, (max_d,)).fetchone()
            if prev and prev[0]:
                signal_date = str(prev[0])
        temp_conn.close()
    
    print(f"计算特征分组 IC — 信号日期: {signal_date} (次日={max_d})", flush=True)
    
    ic_results = compute_group_ics(signal_date)
    
    if isinstance(ic_results, dict) and 'error' in ic_results:
        print(f"❌ {ic_results['error']}", flush=True)
        return json.dumps(ic_results)
    
    ic_results, used_date = ic_results
    save_results(ic_results, used_date)
    
    print(f"\n✅ {used_date} 特征分组 IC:")
    for gname, ginfo in sorted(ic_results.items()):
        ic = ginfo.get('ic')
        if ic is not None:
            flag = '🟢' if abs(ic) >= 0.08 else '🟡' if abs(ic) >= 0.03 else '🔴'
            print(f"  {flag} {gname:10s} IC={ic:+.4f}  n={ginfo['n']}", flush=True)
        else:
            print(f"  ⚪ {gname:10s} 样本不足 n={ginfo.get('n',0)}", flush=True)
    
    return json.dumps(ic_results, ensure_ascii=False)

if __name__ == '__main__':
    main()
