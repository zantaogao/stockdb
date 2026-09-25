#!/usr/bin/env python3
"""融合评分系统 v10 — 40d×70%+20d×30%, feat_tushare v6, 49维管道

特征: 38基础 + 11GTJA = 49维 (与retrain_20d_fixed.py完全一致)
模型: v6_fixed (lgb_reg_20d_v6_fixed.txt + lgb_reg_40d_v6_fixed.txt)
标准化: v6_norm_stats_{20,40}d_v6_fixed.json (49维)

用法: python combined_score_v6.py [--date 2026-07-10] [--write-db]
"""
import duckdb, json, sys, numpy as np, lightgbm as lgb
from pathlib import Path
from datetime import date as dt_date
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 加父目录，让 core 模块能找到

# ── feat_tushare v6 接口 ──
from feat_tushare import (
    compute_features, get_tushare_db, load_index_data,
    standardize_v6 as standardize_fn,
    N_BASE, GTJA_CODES, load_gtja_compact, get_gtja_value,
)

# ── 模型路径 ──
BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'

REG20_MODEL = MODEL_DIR / 'lgb_reg_20d_v6_fixed.txt'
REG40_MODEL = MODEL_DIR / 'lgb_reg_40d_v6_fixed.txt'
NORM_STATS_20D = MODEL_DIR / 'v6_norm_stats_20d_v6_fixed.json'
NORM_STATS_40D = MODEL_DIR / 'v6_norm_stats_40d_v6_fixed.json'

# ── 融合权重 ──
W40, W20 = 0.70, 0.30

# GTJA因子名称 (前11个，与训练一致)
GTJA_NAMES = GTJA_CODES[:11]


# ════════════════ 规则评分函数 ════════════════

def s_mf(mf):
    if mf is None: return None
    m = mf / 1e8
    if m > 10: return 100
    elif m > 5: return 90
    elif m > 2: return 80
    elif m > 1: return 70
    elif m > 0.5: return 60
    elif m > 0: return 50
    elif m == 0: return 30
    else: return 10

def s_mom(c20, c60, d5):
    s = 50
    if c20 < -15: s += 20
    elif c20 < -10: s += 15
    elif c20 < -5: s += 10
    elif c20 < 0: s += 5
    elif c20 > 10: s -= 15
    elif c20 > 5: s -= 5
    if c60 < -25: s += 15
    elif c60 < -15: s += 10
    elif c60 < -5: s += 5
    elif c60 > 10: s -= 10
    elif c60 > 5: s -= 5
    if d5 < -5: s += 15
    elif d5 < -2: s += 10
    elif d5 < 0: s += 5
    elif d5 > 5: s -= 10
    elif d5 > 2: s -= 5
    return max(0, min(100, s))

def s_qual(roe, py, ry):
    if roe is None and py is None: return None
    s = 50
    if roe is not None:
        if roe > 25: s += 25
        elif roe > 20: s += 20
        elif roe > 15: s += 15
        elif roe > 10: s += 10
        elif roe > 5: s += 5
        else: s -= 10
    if py is not None:
        if py > 50: s += 15
        elif py > 30: s += 10
        elif py > 10: s += 5
        elif py > 0: s += 2
        elif py < -30: s -= 15
        elif py < 0: s -= 5
    if ry is not None:
        if ry > 30: s += 10
        elif ry > 15: s += 5
        elif ry > 0: s += 2
        elif ry < -20: s -= 10
        elif ry < 0: s -= 5
    return max(0, min(100, s))

def s_tech(bull, d120, vr):
    s = 50
    if bull: s += 25
    else: s -= 5
    if d120 is not None:
        if -5 <= d120 <= 10: s += 15
        elif 10 < d120 <= 20: s += 5
        elif 20 < d120 <= 35: s += 0
        elif d120 > 35: s -= 10
        elif -15 <= d120 < -5: s += 5
        elif d120 < -15: s -= 10
    if vr is not None:
        if 1.2 <= vr <= 3: s += 10
        elif vr > 3: s += 5
        elif vr < 0.5: s -= 5
    return max(0, min(100, s))

def s_val(pe, pb):
    if pe is None and pb is None: return None
    s = 50
    if pe is not None and pe > 0:
        if pe < 15: s += 25
        elif pe < 25: s += 15
        elif pe < 40: s += 5
        elif pe > 100: s -= 15
        elif pe > 50: s -= 5
    if pb is not None and pb > 0:
        if pb < 1.5: s += 15
        elif pb < 3: s += 10
        elif pb < 5: s += 5
        elif pb > 10: s -= 10
    return max(0, min(100, s))


def is_limit_up(code, close, high, change_pct):
    """判断是否涨停（考虑不同板块的涨跌停幅度）"""
    if change_pct is None or close is None or high is None:
        return False
    
    # 收盘价等于最高价（封板）
    if close < high * 0.995:  # 允许 0.5% 误差
        return False
    
    # 根据板块判断涨停幅度
    if code.startswith('688'):  # 科创板 20%
        return change_pct >= 19.8
    elif code.startswith('3'):  # 创业板 20%
        return change_pct >= 19.8
    elif code.startswith(('002', '30')):  # 中小板/创业板（旧代码）
        return change_pct >= 19.8
    elif 'ST' in str(code) or 'ST' in str(code):  # ST 股 5%
        return change_pct >= 4.8
    else:  # 主板 10%
        return change_pct >= 9.8


# ════════════════ ML特征计算（49维） ════════════════

def compute_49d_features(code, rows, conn, gtja_lookup, idx_close_dict):
    """用feat_tushare v6管道计算49维特征
    
    Args:
        code: stock_code (e.g. '000001')
        rows: list of daily bars [(date, close, open, high, low, change_pct, volume, amount), ...] ascending order
        conn: duckdb connection
        gtja_lookup: dict from load_gtja_compact(), or None
        idx_close_dict: {date_str(YYYY-MM-DD): index_close} 指数收盘数据
    
    Returns: (np.array(49,), date_str) or (None, None) on error
    """
    try:
        closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
        highs = np.array([float(r[3]) for r in rows], dtype=np.float64)
        lows = np.array([float(r[4]) for r in rows], dtype=np.float64)
        volumes = np.array([float(r[6]) if r[6] else 0.0 for r in rows], dtype=np.float64)
        # change_pct stored as percentage (-12.34 means -12.34%), convert to fraction
        pcts = np.array([float(r[5]) / 100.0 if r[5] else 0.0 for r in rows], dtype=np.float64)
        
        dates_str = [str(r[0])[:10].replace('-', '') for r in rows]  # YYYYMMDD
        
        # ── 估值数据 ──
        val_row = conn.execute(
            "SELECT pe_ttm, pb, total_mv FROM stock_valuation "
            "WHERE stock_code=? ORDER BY date DESC LIMIT 1", [code]
        ).fetchone()
        
        val_dict = {}
        if val_row and len(val_row) >= 3:
            pe_val, pb_val, mv_val = val_row
            if pe_val is not None and float(pe_val) > 0:
                val_dict['ep'] = 1.0 / float(pe_val)
            if pb_val is not None and float(pb_val) > 0:
                val_dict['bp'] = 1.0 / float(pb_val)
            if mv_val is not None and float(mv_val) > 0:
                val_dict['ln_cap'] = np.log(float(mv_val))

        # ── 计算38基础特征 (与retrain_20d_fixed.py顺序一致) ──
        feat_base = compute_features(
            closes.tolist(), highs.tolist(), lows.tolist(),
            volumes.tolist(), pcts.tolist(),
            idx_close_dict, val_dict
        )

        # ── GTJA因子（11个） ──
        last_date = dates_str[-1] if dates_str else ''
        
        if gtja_lookup is not None:
            gtja_vals = get_gtja_value(code, last_date, gtja_lookup)
        else:
            # Fallback from stk_factor table
            ts_code = f'{code}.SH' if code.startswith('6') else f'{code}.SZ'
            dt_clean = dates_str[-1] if dates_str else ''
            
            row = conn.execute(
                "SELECT extra FROM stk_factor WHERE ts_code=? AND trade_date=?",
                [ts_code, dt_clean[:8]]  # YYYYMMDD
            ).fetchone()
            
            gtja_vals = _fallback_gtja(row)

        if len(feat_base) != 38 or len(gtja_vals) != 11:
            print(f"  ⚠️ {code}: feature dim mismatch (base={len(feat_base)}, gtja={len(gtja_vals)})")
            return None, None
        
        feat_49d = np.concatenate([feat_base, np.array(gtja_vals[:11], dtype=np.float64)])
        assert len(feat_49d) == 49

        return feat_49d, dates_str[-1] if dates_str else ''
    
    except Exception as e:
        print(f"  ⚠️ ML特征计算失败 [{code}]: {e}")
        import traceback; traceback.print_exc()
        return None, None


def _fallback_gtja(row):
    """从stk_factor extra JSON字段获取GTJA因子值"""
    if not row or not row[0]:
        return [0.0] * 11
    
    try:
        extra = json.loads(row[0])
        vals = [0.0] * 11
        for factor_name, idx in [('kdj_k_bfq', 0), ('atr_bfq', 1), ('rsi_bfq_12', 2)]:
            if factor_name in extra:
                try: vals[idx] = float(extra[factor_name])
                except: pass
        return vals
    except Exception:
        return [0.0] * 11


# ════════════════ 市场风险评分（上证指数） ════════════════

def calc_market_risk(conn):
    """计算市场状态评分,返回0~1"""
    try:
        rows = conn.execute("""
            SELECT close, volume FROM index_daily 
            WHERE index_code='000001' ORDER BY date DESC LIMIT 120
        """).fetchall()
        
        if len(rows) < 60: return None
        
        closes_idx = [float(r[0]) for r in rows][::-1]  # ascending
        vols_idx = [float(r[1]) if r[1] else 0 for r in rows][::-1]
        
        ma60_now = sum(closes_idx[-60:]) / 60.0
        ma60_prev = sum(closes_idx[-80:-20]) / 60.0 if len(closes_idx) >= 80 else ma60_now
        
        slope_val = (ma60_now / max(ma60_prev, 0.01) - 1) * 100
        trend_s = 1.0 / (1.0 + np.exp(-(slope_val - 1.0) * 1.5))
        
        rets_idx = [closes_idx[i] / closes_idx[i-1] - 1 for i in range(1, len(closes_idx))]
        vol20 = np.std(rets_idx[-20:]) * np.sqrt(252) if len(rets_idx) >= 20 else 20.0
        vol_s = max(0.0, min(1.0, 1 - (vol20 - 15) / 25))
        
        mv5 = sum(vols_idx[-5:]) / 5.0
        mv20 = sum(vols_idx[-20:]) / 20.0
        mp5 = sum(closes_idx[-5:]) / 5.0
        mp20 = sum(closes_idx[-20:]) / 20.0
        
        confirm_s = (1.0 if (mv5/mv20 > 1 and mp5/mp20 > 1) or 
                       (mv5/mv20 < 1 and mp5/mp20 < 1) else 0.5)
        
        return trend_s * 0.4 + vol_s * 0.3 + confirm_s * 0.3
    except: 
        return None


# ════════════════ 主评分流程 ════════════════

def main():
    ref_date_str = None
    for i, a in enumerate(sys.argv):
        if a == '--date' and i+1 < len(sys.argv):
            ref_date_str = sys.argv[i+1]
    
    today = dt_date.fromisoformat(ref_date_str) if ref_date_str else dt_date.today()
    today_str = today.isoformat()

    print("=" * 70)
    print("融合评分系统 v10 — feat_tushare_v6 (49维管道)")
    print(f"  日期: {today_str} | 模型: v6_fixed(20d+40d) | 权重: 40d×70% + 20d×30%")
    print("=" * 70)

    # ── 加载模型 ──
    reg20_model = None; stats20 = {}
    reg40_model = None; stats40 = {}
    
    if REG20_MODEL.exists():
        reg20_model = lgb.Booster(model_file=str(REG20_MODEL))
        n_trees_20 = reg20_model.num_trees()
        print(f"✅ 20日 v6_fixed模型已加载 ({n_trees_20}棵树, {N_BASE+11}维)")
    else:
        print(f"⚠️ 20d模型不存在: {REG20_MODEL}")
    
    if REG40_MODEL.exists():
        reg40_model = lgb.Booster(model_file=str(REG40_MODEL))
        n_trees_40 = reg40_model.num_trees()
        print(f"✅ 40日 v6_fixed模型已加载 ({n_trees_40}棵树, {N_BASE+11}维)")
    else:
        print(f"⚠️ 40d模型不存在: {REG40_MODEL}")

    # ── norm_stats ──
    if NORM_STATS_20D.exists():
        with open(NORM_STATS_20D) as f: stats20 = json.load(f)
        n_s = len([k for k in stats20 if not k.startswith('_')])
        print(f"✅ 20d norm_stats已加载 ({n_s}维)")

    if NORM_STATS_40D.exists():
        with open(NORM_STATS_40D) as f: stats40 = json.load(f)
        n_s = len([k for k in stats40 if not k.startswith('_')])
        print(f"✅ 40d norm_stats已加载 ({n_s}维)")

    # ── 连接数据库 ──
    # 评分数据写入 state.db (signal_history 表在那里)
    from core.db import get_state_db, get_tushare_db
    conn_state = get_state_db()
    
    # 读取数据用 tushare.db (只读)
    conn_tushare = get_tushare_db()
    
    # 统一用 conn_tushare 读数据，conn_state 写信号

    # ── 指数数据（上证指数） ──
    print("\n预加载指数数据...")
    idx_close_dict = load_index_data()
    print(f"  ✅ {len(idx_close_dict)}个交易日已加载")

    # ── GTJA 因子 ──
    print("预加载 GTJA 因子...")
    gtja_lookup = load_gtja_compact()
    if gtja_lookup:
        n_factors = len([k for k in gtja_lookup.keys() 
                        if not k.startswith('_') and isinstance(gtja_lookup[k], dict)])
        print(f"  ✅ GTJA loaded ({n_factors}个因子)")
    else:
        print("  ⚠️ GTJA 未加载，将使用 stk_factor 表或零值")

    # ── 市场风险 ──
    market_risk = calc_market_risk(conn_tushare)
    if market_risk is not None:
        mr_label = "🟢偏多" if market_risk > 0.6 else \
                   ("⚪中性" if market_risk > 0.4 else "🔴偏弱")
        print(f"✅ 市场风险评分: {market_risk:.2f} ({mr_label})")

    # ── 全量选股（从 stock_basic 获取所有上市股票） ──
    print("\n📊 全量选股评分...")
    
    # 获取所有上市股票（delist_date 为空表示未退市）
    stocks = conn_tushare.execute("""
        SELECT ts_code, name FROM stock_basic 
        WHERE delist_date IS NULL
        ORDER BY ts_code
    """).fetchall()
    
    print(f"  共 {len(stocks)} 只股票 (预计需要 8-12 分钟)")
    
    results = []
    
    for i, (code, name) in enumerate(stocks):
        # 进度输出（每 100 只股票）
        if (i + 1) % 100 == 0:
            print(f"  已处理 {i+1}/{len(stocks)} 只股票...")
        
        # 去掉 .SH/.SZ 后缀
        code_short = code.split('.')[0]
        
        # ── 获取日线数据（降序→反转成升序） ──
        date_filter = f" AND date<='{today_str}'" if ref_date_str else ""
        
        rows = conn_tushare.execute(f"""
            SELECT date, close, open, high, low, 
                   COALESCE(change_pct, 0), volume, amount
            FROM stock_daily WHERE stock_code='{code_short}'{date_filter} 
            ORDER BY date DESC LIMIT 120
        """).fetchall()
        
        if not rows or len(rows) < 60:
            continue
        
        # Reverse to ascending (oldest first, newest last) — matches training format
        rows = rows[::-1]
        
        closes_arr = [float(r[1]) for r in rows]
        lc = closes_arr[-1]

        # ── 打板检测 ──
        # 获取当日 change_pct（rows[-1] 是当日数据）
        today_row = rows[-1]
        today_change_pct = float(today_row[5]) if len(today_row) > 5 else 0
        today_high = float(today_row[3]) if len(today_row) > 3 else lc
        today_close = float(today_row[1]) if len(today_row) > 1 else lc
        
        is_daban = is_limit_up(code_short, today_close, today_high, today_change_pct)
        
        # ── 规则评分用数据 ──
        ma60 = np.mean(closes_arr[-60:]) if len(closes_arr) >= 60 else lc
        ma120 = np.mean(closes_arr)
        
        bull_cond = (np.mean(closes_arr[-5:]) > np.mean(closes_arr[-10:]) > 
                     np.mean(closes_arr[-20:]) > ma60 if len(closes_arr) >= 60 else False)
        dev120 = (lc / max(ma120, 0.01) - 1) * 100
        
        chg20 = (lc / closes_arr[-20] - 1) * 100 if len(closes_arr) >= 20 else 0
        chg60 = (lc / closes_arr[-60] - 1) * 100 if len(closes_arr) >= 60 else 0
        d5_chg = (lc / closes_arr[-6] - 1) * 100 if len(closes_arr) >= 6 else 0
        
        vols_20d = np.array([float(r[6]) for r in rows[-20:]] + [1e9])
        vr_val = float(vols_20d[-1] / max(np.mean(vols_20d), 1))

        # ── 资金流（今年 5 月以来累计） ──
        mf_year = str(today.year) + '-05-01'
        mf_row = conn_tushare.execute(
            f"SELECT COALESCE(SUM(main_net), 0) FROM money_flow "
            f"WHERE stock_code='{code_short}' AND date >= '{mf_year}'"
        ).fetchone()
        mf_val = float(mf_row[0])

        # ── 财务数据（简化版，用可用字段） ──
        # fin_income 表没有 roe/profit_yoy/revenue_yoy，用 eps 和 revenue
        fin_row = conn_tushare.execute(
            "SELECT eps, revenue FROM fin_income "
            "WHERE ts_code=? ORDER BY end_date DESC LIMIT 1",
            [code]
        ).fetchone()
        
        # 财务评分简化：只看是否有盈利
        roe = float(fin_row[0]) if fin_row and fin_row[0] else None  # eps 作为替代
        py = None  # 利润同比需要计算，暂时跳过
        ry = float(fin_row[1]) if fin_row and fin_row[1] else None  # total_revenue

        # ── 估值数据 ──
        val_row = conn_tushare.execute(
            "SELECT pe_ttm, pb FROM stock_valuation "
            "WHERE stock_code=? ORDER BY date DESC LIMIT 1",
            [code_short]
        ).fetchone()

        # ── 规则评分 ──
        rs_list = []
        
        ms = s_mf(mf_val)
        if ms is not None: rs_list.append(ms * WEIGHTS['money_flow'])
        
        rs_list.append(s_mom(chg20, chg60, d5_chg) * WEIGHTS['momentum'])
        
        # 打板加分（涨停 +25 分）
        if is_daban:
            rs_list.append(100 * WEIGHTS['momentum'])  # 涨停直接给满分
            # print(f"  🚀 {code} 涨停加分 +25")
        
        qs = s_qual(
            roe,
            py,
            ry
        )
        if qs is not None: rs_list.append(qs * WEIGHTS['quality'])
        
        rs_list.append(s_tech(bull_cond, dev120, vr_val) * WEIGHTS['technical'])
        
        vs = s_val(
            float(val_row[0]) if val_row and val_row[0] else None,
            float(val_row[1]) if val_row and val_row[1] else None
        )
        if vs is not None: rs_list.append(vs * WEIGHTS['valuation'])
        
        rule_score = sum(rs_list) / len(rs_list) if rs_list else 50.0

        # ── ML 预测 — 49 维特征 ──
        feat_49d, _ = compute_49d_features(
            code, rows, conn_tushare, gtja_lookup, idx_close_dict
        )
        
        reg20_pred = 0.0; reg40_pred = 0.0
        
        if feat_49d is not None and len(feat_49d) == 49:
            f_arr = np.nan_to_num(feat_49d.reshape(1, -1), nan=0.0)
            
            if reg20_model and stats20:
                f_std = standardize_fn(f_arr, stats20)
                try:
                    reg20_pred = float(reg20_model.predict(f_std)[0])
                except Exception as e:
                    print(f"  ⚠️ {code} 20d预测失败: {e}")

            if reg40_model and stats40:
                f_std_40 = standardize_fn(f_arr, stats40)
                try:
                    reg40_pred = float(reg40_model.predict(f_std_40)[0])
                except Exception as e:
                    print(f"  ⚠️ {code} 40d预测失败: {e}")

        # ── 分数映射到[0,100] ──
        reg20_score = max(0.0, min(100.0, (reg20_pred + 10) / 20 * 100))
        reg40_score = max(0.0, min(100.0, (reg40_pred + 10) / 20 * 100))

        # ── 融合评分 ──
        if reg40_model:
            composite = reg40_score * W40 + reg20_score * W20
        else:
            composite = reg20_score
        
        # ── 结论和位置判断 ──
        if composite >= 75: conclusion = "🟢 强烈推荐"
        elif composite >= 60: conclusion = "🟡 推荐关注" 
        elif composite >= 45: conclusion = "⚪ 观察中"
        else: conclusion = "🔴 不参与"

        if dev120 > 35: pos_v = "⚠️追高"
        elif dev120 > 20: pos_v = "偏高" if not bull_cond else "多头合理"
        elif dev120 < -15: pos_v = "💀破位"
        elif dev120 < -5: pos_v = "超卖区"
        else: pos_v = "合理✅"

        results.append({
            'code': code, 'name': name, 'price': lc,
            'composite': composite,
            'reg40_pred': reg40_pred, 'reg40_score': reg40_score,
            'reg20_pred': reg20_pred, 'reg20_score': reg20_score,
            'rule_score': rule_score,
            'dev120': dev120, 'bull': bull_cond,
            'conclusion': conclusion, 'pos': pos_v,
            'is_daban': is_daban,
        })

    # ── 排序输出 ──
    results.sort(key=lambda x: x['composite'], reverse=True)

    print(f"\n{'排名':>4} {'代码':7s} {'名称':10s} {'融合分':>6s} "
          f"{'40d预':>8s} {'20d预':>8s} {'年线偏':>7s} {'位置':10s} {'结论'}")
    print(f"{'─'*95}")

    for i, r in enumerate(results, 1):
        print(f"{i:>4} {r['code']:7s} {r['name'][:10]:10s} "
              f"{r['composite']:>6.0f}  "
              f"{r['reg40_pred']:>+8.2f} {r['reg20_pred']:>+8.2f} "
              f"{r['dev120']:>+6.0f}% {r['pos']:10s} {r['conclusion']}")

    # ── 汇总 ──
    buys = [r for r in results if r['composite'] >= 60]
    watches = [r for r in results if 45 <= r['composite'] < 60]
    
    print(f"\n{'='*70}\n📋 执行清单\n{'='*70}")
    
    if buys:
        print(f"\n🟢 推荐/强烈推荐 ({len(buys)}只):")
        for r in buys[:20]:
            daban_tag = " 🚀" if r.get('is_daban') else ""
            print(f"  {r['code']:7s} {r['name'][:10]:10s} "
                  f"融合分={r['composite']:.0f}{daban_tag} | "
                  f"40d={r['reg40_pred']:+.2f}% | 20d={r['reg20_pred']:+.2f}%")
    
    if watches:
        print(f"\n⚪ 观察中 ({len(watches)}只):")
        for r in watches[:10]:
            print(f"  {r['code']:7s} {r['name'][:10]:10s} "
                  f"融合分={r['composite']:.0f} | "
                  f"40d={r['reg40_pred']:+.2f}%")

    # ── 写结果到文件（供Hermes Dashboard读取） ──
    score_dir = Path.home() / '.hermes' / 'stockdb'
    
    result_file = score_dir / 'score_results.json'
    
    # Serialize results: convert numpy types to native Python for JSON serialization
    def _sanitize_val(v):
        """Convert numpy types and bools to native Python scalars"""
        try:
            if isinstance(v, (np.integer,)): return int(v)
            elif isinstance(v, (np.floating,)): return float(v)
            elif isinstance(v, np.bool_): return bool(v)  # already native bool
            elif isinstance(v, (bool, str, int, float, type(None))): return v
            else: return str(v) if not isinstance(v, dict) or all(isinstance(k, str) for k in v.keys()) else {k: _sanitize_val(val) for k, val in v.items()}
        except Exception:
            return str(v)
    
    safe_results = [_sanitize_val(r) for r in results]
    safe_buys = [{'code': r['code'], 'name': r['name'], 
                  'composite': int(round(r['composite']))} for r in buys[:20]]
    
    with open(result_file, 'w') as f:
        json.dump({
            'date': today_str,
            'results': safe_results,
            'buys': safe_buys,
        }, f, ensure_ascii=False)

    # ── 缓存 ──
    cache_data = {'date': today_str, '_version': '10',
                  'scores': {r['code']: r['composite'] for r in results}}
    with open(score_dir / '_score_cache.json', 'w') as f:
        json.dump(cache_data, f)

    # ── 写入 DB（--write-db 模式） ──
    if '--write-db' in sys.argv or '--db' in sys.argv:
        print(f"\n💾 写入 DB 信号历史...")
        
        # 先删除今天的旧数据
        # 删当日旧数据（兼容两种日期格式）
        conn_state.execute(f"DELETE FROM signal_history WHERE REPLACE(date,'-','')='{today_str.replace('-','')}'")
        
        inserted = 0
        failed = 0
        for r in results:
            try:
                conn_state.execute("""
                    INSERT OR REPLACE INTO signal_history
                    (date, stock_code, stock_name, industry,
                     fusion_score, reg20, reg40, reg10, gtja_score, deviation120,
                     final_score, fusion_avg, cls27_prob, lstm,
                     reg_pred, reg10_pred, reg40_pred, is_limit_up)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    today_str, r['code'], r['name'], '',
                    round(r['composite'], 1),
                    round(r['reg20_pred'], 4),
                    round(r['reg40_pred'], 4),
                    None, None, round(r['dev120'], 4),
                    round(r['composite'], 1), round(r['composite'], 1),
                    0.5, 50.0,
                    round(r['reg20_pred'], 4), None, round(r['reg40_pred'], 4),
                    r.get('is_daban', False),
                ])
                inserted += 1
                if inserted % 500 == 0:
                    conn_state.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    print(f"  已写入 {inserted} 条...")
            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"  ⚠️ 写入失败 [{r['code']}]: {str(e)[:80]}")
        
        conn_state.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print(f"✅ 已写入 {inserted} 条信号 (共{len(results)}只，失败{failed}条)")
    
    conn_tushare.close()
    conn_state.close()
    
    print(f"\n📄 结果已保存到: {result_file}")


# ── 规则权重常量 ──
WEIGHTS = {
    'money_flow': 25,
    'momentum': 35,
    'quality': 25,
    'technical': 20,
    'valuation': 15,
}


if __name__ == '__main__':
    main()
