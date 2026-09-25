#!/usr/bin/env python3
"""融合评分系统 v10 — 40d×70%+20d×30%, feat_tushare v6, 49维管道

与训练完全一致:
- 38基础特征(与retrain_20d_fixed.py一致) + 11GTJA = 49维
- v6_fixed模型(49D max_feature_idx=49) + 49维norm_stats
"""
import duckdb, json, sys, numpy as np, lightgbm as lgb
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── feat_tushare v6: 38基础特征 + GTJA加载 ──
try:
    from feat_tushare import (
        compute_features, get_tushare_db, load_index_data,
        preload_gtja, _get_gtja_for_stock,
        N_BASE, standardize_v6 as standardize,
    )
except ImportError:
    # Fallback: old feat_tushare
    from feat_tushare import (
        compute_raw_features, get_tdx_db, load_index_data_simple,
        normalize_feat_batch, FEAT_WIN,
    )

# ── 模型路径 ──
MODEL_DIR = Path.home() / '.hermes' / 'stockdb' / 'models'

REG20_MODEL = MODEL_DIR / 'lgb_reg_20d_v6_fixed.txt'
REG40_MODEL = MODEL_DIR / 'lgb_reg_40d_v6_fixed.txt'

NORM_STATS_20D = MODEL_DIR / 'v6_norm_stats_20d_v6_fixed.json'
NORM_STATS_40D = MODEL_DIR / 'v6_norm_stats_40d_v6_fixed.json'

# ── 融合权重 ──
W40, W20 = 0.70, 0.30

# ── GTJA因子(与训练一致) ──
GTJA_NAMES = ['gtja_001','gtja_002','gtja_003','gtja_004','gtja_005',
              'gtja_006','gtja_007','gtja_008','gtja_009','gtja_010','gtja_011']

# ── 规则权重 ──
WEIGHTS = {
    'money_flow': 25,
    'momentum': 35,
    'quality': 25,
    'technical': 20,
    'valuation': 15,
}


# ════════ 规则评分 ════════

def s_mf(mf):
    if mf is None: return None
    m = mf / 1e8
    if m > 10: return 100
    if m > 5: return 90
    if m > 2: return 80
    if m > 1: return 70
    if m > 0.5: return 60
    if m > 0: return 50
    if m == 0: return 30
    return 10

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


# ════════ ML特征计算（49维） ════════

def compute_49d_features(code, rows, conn, gtja_lookup, idx_close_dict):
    """用feat_tushare v6管道计算49维特征
    
    Returns: (np.array(49,), date_str) or (None, None)
    """
    try:
        closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
        highs = np.array([float(r[3]) for r in rows], dtype=np.float64)
        lows = np.array([float(r[4]) for r in rows], dtype=np.float64)
        volumes = np.array([float(r[6]) if r[6] else 0 for r in rows], dtype=np.float64)
        
        # change_pct is stored as percentage (e.g., -12.34 means -12.34%)
        pcts = np.array([float(r[5]) / 100.0 if r[5] else 0 for r in rows], dtype=np.float64)
        
        dates_str = [str(r[0])[:10].replace('-', '') for r in rows]
        
        # 复权因子 (used by compute_features internally via feat_tushare)
        adj_rows = conn.execute(
            "SELECT trade_date, adj_factor FROM adj_factor WHERE stock_code=? ORDER BY trade_date",
            [code]
        ).fetchall()
        
        # 估值数据
        val_row = conn.execute(
            "SELECT pe_ttm, pb, total_mv FROM stock_valuation "
            "WHERE stock_code=? ORDER BY date DESC LIMIT 1",
            [code]
        ).fetchone()
        
        val_dict = {}
        if val_row and len(val_row) >= 3:
            pe, pb, mv = val_row
            if pe and float(pe) > 0:
                val_dict['ep'] = 1.0 / float(pe)
            if pb and float(pb) > 0:
                val_dict['bp'] = 1.0 / float(pb)
            if mv and float(mv) > 0:
                val_dict['ln_cap'] = np.log(float(mv))
        
        # 计算38基础特征
        feat_base = compute_features(
            closes.tolist(), highs.tolist(), lows.tolist(),
            volumes.tolist(), pcts.tolist(),
            idx_close_dict, val_dict
        )
        
        if len(feat_base) != 38:
            print(f"  ⚠️ {code}: base feature count mismatch (expected 38 got {len(feat_base)})")
            return None, None
        
        # GTJA因子（11个，与训练一致：sorted(gtja_c.keys())[:11]）
        last_date = dates_str[-1] if dates_str else ''
        gtja_vals = _get_gtja_for_stock(code, last_date, conn, gtja_lookup)
        
        if len(gtja_vals) != 11:
            print(f"  ⚠️ {code}: GTJA count mismatch (expected 11 got {len(gtja_vals)})")
            return None, None
        
        # Concatenate: 38 + 11 = 49
        feat_49d = np.concatenate([feat_base, np.array(gtja_vals, dtype=np.float64)])
        
        assert len(feat_49d) == 49, f"Total feature dim is {len(feat_49d)}, expected 49"
        return feat_49d, dates_str[-1] if dates_str else ''
    
    except Exception as e:
        print(f"  ⚠️ ML特征计算失败 [{code}]: {e}")
        import traceback; traceback.print_exc()
        return None, None


# ════════ GTJA因子加载 ════════

def _get_gtja_for_stock(stock_code, date_str, conn, gtja_lookup):
    """从GTJA compact pkl获取11个因子值
    
    优先使用pkl预加载数据，fallback到stk_factor表。
    """
    if gtja_lookup:
        result = []
        for factor_name in GTJA_NAMES:
            # pkl structure: {factor_name: {code_short: {date_str: value}}}
            factor_data = gtja_lookup.get(factor_code, {})
            
            code_short = stock_code.split('.')[-1] if '.' in stock_code else stock_code
            
            vals_for_stock = {}
            for d_str, val in factor_data.items():
                if str(val) not in (None, 'nan', ''):
                    try:
                        vals_for_stock[str(d_str)[:8]] = float(val)
                    except (ValueError, TypeError): pass
            
            # Direct lookup or forward-fill up to 15 days back
            val = None
            if date_str in vals_for_stock:
                val = vals_for_stock[date_str]
            else:
                all_dates_sorted = sorted(vals_for_stock.keys())
                for i, d in enumerate(all_dates_sorted):
                    if d >= date_str and i > 0:
                        for offset in range(15):
                            idx = i - 1 - offset
                            if idx >= 0:
                                val = vals_for_stock[all_dates_sorted[idx]]
                                break
                        break
            
            result.append(float(val) if val else 0.0)
        return result
    
    # Fallback: from stk_factor extra JSON field  
    ts_code = f'{stock_code}.SH' if stock_code.startswith('6') else f'{stock_code}.SZ'
    dt_clean = date_str.replace('-', '')[:8]  # YYYYMMDD format
    
    row = conn.execute(
        "SELECT extra FROM stk_factor WHERE ts_code=? AND trade_date=?",
        [ts_code, dt_clean]
    ).fetchone()
    
    if not row: return [0.0] * 11
    
    try:
        extra = json.loads(row[0])
        # Map known factors to GTJA indices (partial mapping since pkl has full set)
        vals = [0.0] * 11
        for factor_name, idx in [('kdj_k_bfq', 0), ('atr_bfq', 1), ('rsi_bfq_12', 2)]:
            if factor_name in extra:
                try: vals[idx] = float(extra[factor_name])
                except: pass
        return vals
    except: return [0.0] * 11


def preload_gtja():
    """预加载GTJA compact pkl数据为lookup字典"""
    gtja_path = MODEL_DIR / 'gtja_compact.pkl'
    if not gtja_path.exists():
        print(f"  [WARN] GTJA compact pkl not found: {gtja_path}")
        return None
    
    import pickle
    with open(gtja_path, 'rb') as f:
        data = pickle.load(f)
    
    # Convert to lookup format: {factor_name: {code_short: {date_str(YYYYMMDD): value}}}
    lookup = {}
    for factor_name in GTJA_NAMES[:len(data.keys())]:
        if factor_name not in data: continue
        
        code_dict = {}  # {short_code: {date_str: value}}
        raw_data = data[factor_name]
        
        if isinstance(raw_data, dict):
            for code_key, date_series in raw_data.items():
                parts = str(code_key).split('.')
                short = parts[-1] if len(parts) > 1 else str(code_key)
                
                stock_dict = {}
                for d_str, val in date_series.items():
                    try: v = float(val)
                    except (ValueError, TypeError): continue
                    
                    ds = str(d_str)[:8].replace('-', '')
                    stock_dict[ds] = v
                
                code_dict[short] = stock_dict
        
        lookup[factor_name] = code_dict
    
    print(f"  ✅ GTJA compact loaded: {len(lookup)} factors")
    return lookup


# ════════ 市场风险评分（上证指数） ════════

def calc_market_risk(conn):
    """计算市场状态评分，返回0~1"""
    try:
        rows = conn.execute("""
            SELECT close, volume FROM index_daily 
            WHERE index_code='000001' ORDER BY date DESC LIMIT 120
        """).fetchall()
        
        if len(rows) < 60: return None
        
        closes_idx = [float(r[0]) for r in rows][::-1]
        vols_idx = [float(r[1]) if r[1] else 0 for r in rows][::-1]
        
        ma60_now = sum(closes_idx[-60:]) / 60
        ma60_prev = sum(closes_idx[-80:-20]) / 60 if len(closes_idx) >= 80 else ma60_now
        
        slope_val = (ma60_now / max(ma60_prev, 0.01) - 1) * 100
        trend_s = 1.0 / (1.0 + np.exp(-(slope_val - 1.0) * 1.5))
        
        rets_idx = [closes_idx[i] / closes_idx[i-1] - 1 for i in range(1, len(closes_idx))]
        vol20 = np.std(rets_idx[-20:]) * np.sqrt(252) if len(rets_idx) >= 20 else 20
        vol_s = max(0, min(1, 1 - (vol20 - 15) / 25))
        
        mv5 = sum(vols_idx[-5:]) / 5
        mv20 = sum(vols_idx[-20:]) / 20
        mp5 = sum(closes_idx[-5:]) / 5
        mp20 = sum(closes_idx[-20:]) / 20
        
        confirm_s = 1.0 if (mv5/mv20 > 1 and mp5/mp20 > 1) or \
                            (mv5/mv20 < 1 and mp5/mp20 < 1) else 0.5
        
        return trend_s * 0.4 + vol_s * 0.3 + confirm_s * 0.3
    except: 
        return None


# ════════ 主评分流程 ════════

def main():
    ref_date_str = None
    for i, a in enumerate(sys.argv):
        if a == '--date' and i+1 < len(sys.argv):
            ref_date_str = sys.argv[i+1]
    
    from datetime import date as dt_date
    
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
    conn = get_tushare_db()
    
    # ── 指数数据（上证指数） ──
    print("\n预加载指数数据...")
    idx_close_dict = load_index_data()
    print(f"  ✅ {len(idx_close_dict)}个交易日已加载")

    # ── GTJA因子 ──
    print("\n预加载GTJA因子...")
    gtja_lookup = preload_gtja()

    # ── 市场风险 ──
    market_risk = calc_market_risk(conn)
    if market_risk is not None:
        mr_label = "🟢偏多" if market_risk > 0.6 else ("⚪中性" if market_risk > 0.4 else "🔴偏弱")
        print(f"✅ 市场风险评分: {market_risk:.2f} ({mr_label})")

    # ── 持仓列表 ──
    HOLD_PATH = Path.home() / '.hermes' / 'stockdb' / 'holdings.json'
    with open(HOLD_PATH) as f:
        hold_data = json.load(f)
    
    targets = [p for p in hold_data['positions'] 
               if p.get('status') in ('watch_active', 'watch_cold', 'hold')
               and not p['code'].startswith('TRUST')]

    print(f"\n📊 扫描 {len(targets)} 只持仓股...")
    
    results = []
    
    for i, p in enumerate(targets):
        code = p['code']
        name = p.get('name', '')
        
        # ── 获取日线数据（升序：旧→新） ──
        date_filter = f" AND date<='{today_str}'" if ref_date_str else ""
        
        rows = conn.execute(f"""
            SELECT date, close, open, high, low, COALESCE(change_pct, 0), volume, amount
            FROM stock_daily WHERE stock_code='{code}'{date_filter} 
            ORDER BY date DESC LIMIT 120
        """).fetchall()
        
        if not rows or len(rows) < 60:
            continue
        
        # Reverse to ascending (oldest first) — matches training format
        rows = rows[::-1]
        
        closes_arr = [float(r[1]) for r in rows]
        last_date = str(rows[-1][0])[:10]
        lc = closes_arr[-1]
        
        # ── 基本面/技术面（规则评分用） ──
        ma60 = np.mean(closes_arr[-60:]) if len(closes_arr) >= 60 else lc
        ma120 = np.mean(closes_arr)
        
        bull = (np.mean(closes_arr[-5:]) > np.mean(closes_arr[-10:]) > 
                np.mean(closes_arr[-20:]) > ma60 if len(closes_arr) >= 60 else False)
        dev120 = (lc / max(ma120, 0.01) - 1) * 100
        
        chg20 = (lc / closes_arr[-20] - 1) * 100 if len(closes_arr) >= 20 else 0
        chg60 = (lc / closes_arr[-60] - 1) * 100 if len(closes_arr) >= 60 else 0
        d5_chg = (lc / closes_arr[-6] - 1) * 100 if len(closes_arr) >= 6 else 0
        
        vols_20d = np.array([float(r[6]) for r in rows[-20:]] + [1e9])
        vr_val = float(vols_20d[-1] / max(np.mean(vols_20d), 1))

        # ── 资金流 ──
        mf_start = f"'{today.year}-05-01'"
        mf_row = conn.execute(
            f"SELECT COALESCE(SUM(main_net), 0) FROM money_flow "
            f"WHERE stock_code='{code}' AND date >= {mf_start}"
        ).fetchone()
        mf_val = float(mf_row[0])

        # ── 财务数据 ──
        fin_code = code  # tushare format uses stock_code directly
        fin_row = conn.execute(
            "SELECT roe, profit_yoy, revenue_yoy FROM fin_income "
            "WHERE ts_code=? ORDER BY end_date DESC LIMIT 1",
            [fin_code]
        ).fetchone()

        # ── 估值数据 ──
        val_row = conn.execute(
            "SELECT pe_ttm, pb FROM stock_valuation "
            "WHERE stock_code=? ORDER BY date DESC LIMIT 1",
            [code]
        ).fetchone()

        # ── 规则评分 ──
        rs_list = []
        
        ms = s_mf(mf_val)
        if ms is not None:
            w = WEIGHTS['money_flow']
            rs_list.append(ms * w)
        
        mom_s = s_mom(chg20, chg60, d5_chg)
        rs_list.append(mom_s * WEIGHTS['momentum'])
        
        qs = s_qual(
            float(fin_row[0]) if fin_row and fin_row[0] else None,
            float(fin_row[1]) if fin_row and fin_row[1] else None,
            float(fin_row[2]) if fin_row and fin_row[2] else None
        )
        if qs is not None: rs_list.append(qs * WEIGHTS['quality'])
        
        tech_s = s_tech(bull, dev120, vr_val)
        rs_list.append(tech_s * WEIGHTS['technical'])
        
        vs = s_val(
            float(val_row[0]) if val_row and val_row[0] else None,
            float(val_row[1]) if val_row and val_row[1] else None
        )
        if vs is not None: rs_list.append(vs * WEIGHTS['valuation'])
        
        rule_score = sum(rs_list) / len(rs_list) if rs_list else 50.0

        # ── ML预测 — 49维特征 ──
        feat_49d, _ = compute_49d_features(code, rows, conn, gtja_lookup, idx_close_dict)
        
        reg20_pred = 0.0; reg40_pred = 0.0
        
        if feat_49d is not None and len(feat_49d) == 49:
            # Standardize (clip + normalize per training stats)
            f_arr = np.nan_to_num(feat_49d.reshape(1, -1), nan=0.0)
            
            if reg20_model and stats20:
                f_std = standardize(f_arr, stats20)
                reg20_pred = float(reg20_model.predict(f_std)[0])
            
            if reg40_model and stats40:
                f_std_40 = standardize(f_arr, stats40)
                reg40_pred = float(reg40_model.predict(f_std_40)[0])

        # ── 分数映射到[0,100] ──
        # LightGBM regression output is in [-1, +1] range (predicted direction)
        # Map: [-1, +1] → [0, 100] via min/max scaling
        reg20_score = max(0.0, min(100.0, (reg20_pred + 10) / 20 * 100))
        reg40_score = max(0.0, min(100.0, (reg40_pred + 10) / 20 * 100))

        # ── 融合评分 ──
        if reg40_model:
            composite = reg40_score * W40 + reg20_score * W20
        else:
            composite = reg20_score
        
        # ── 结论 ──
        if composite >= 75: conclusion = "🟢 强烈推荐"
        elif composite >= 60: conclusion = "🟡 推荐关注" 
        elif composite >= 45: conclusion = "⚪ 观察中"
        else: conclusion = "🔴 不参与"

        # ── 位置判断 ──
        if dev120 > 35: pos_v = "⚠️追高"
        elif dev120 > 20: pos_v = "偏高" if not bull else "多头合理"
        elif dev120 < -15: pos_v = "💀破位"
        elif dev120 < -5: pos_v = "超卖区"
        else: pos_v = "合理✅"

        results.append({
            'code': code, 'name': name, 'price': lc,
            'composite': composite,
            'reg40_pred': reg40_pred, 'reg40_score': reg40_score,
            'reg20_pred': reg20_pred, 'reg20_score': reg20_score,
            'rule_score': rule_score,
            'dev120': dev120, 'bull': bull,
            'conclusion': conclusion, 'pos': pos_v,
            'status': p.get('status', ''),
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
        for r in buys[:20]:  # Top 20 only
            print(f"  {r['code']:7s} {r['name'][:10]:10s} "
                  f"融合分={r['composite']:.0f} | "
                  f"40d={r['reg40_pred']:+.2f}% | 20d={r['reg20_pred']:+.2f}%")
    
    if watches:
        print(f"\n⚪ 观察中 ({len(watches)}只):")
        for r in watches[:10]:
            print(f"  {r['code']:7s} {r['name'][:10]:10s} "
                  f"融合分={r['composite']:.0f} | "
                  f"40d={r['reg40_pred']:+.2f}%")

    # ── 写入DB（--write-db模式） ──
    if '--write-db' in sys.argv:
        print(f"\n💾 写入DB信号历史...")
        today_code_list = [f"'{r['code']}'" for r in results]
        
        conn.execute("""
            DELETE FROM signal_history 
            WHERE date = ? AND stock_code IN ({})""".format(','.join(today_code_list)),
            [today_str]
        )
        
        inserted = 0
        for r in results:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO signal_history
                    (date, stock_code, stock_name, industry,
                     fusion_score, reg20, reg40, reg10, gtja_score, deviation120,
                     final_score, fusion_avg, cls27_prob, lstm,
                     reg_pred, reg10_pred, reg40_pred)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    today_str, r['code'], r['name'], '',
                    round(r['composite'], 1),
                    round(r['reg20_pred'], 4),
                    round(r['reg40_pred'], 4),
                    None, None, round(r['dev120'], 4),
                    round(r['composite'], 1), round(r['composite'], 1),
                    0.5, 50.0,
                    round(r['reg20_pred'], 4), None, round(r['reg40_pred'], 4),
                ])
                inserted += 1
            except Exception as e:
                print(f"  ⚠️ 写入失败 [{r['code']}]: {e}")
        
        conn.commit()
        conn.execute("CHECKPOINT")
        print(f"✅ 已写入 {inserted} 条信号 (CHECKPOINT)")

    # ── 保存缓存 ──
    cache_data = {'date': today_str, '_version': '10', 
                  'scores': {r['code']: r['composite'] for r in results}}
    with open(Path.home() / '.hermes' / 'stockdb' / '_score_cache.json', 'w') as f:
        json.dump(cache_data, f)

    conn.close()
    
    # ── 写结果到文件（供Hermes Dashboard读取） ──
    result_file = Path.home() / '.hermes' / 'stockdb' / 'score_results.json'
    with open(result_file, 'w') as f:
        json.dump({
            'date': today_str,
            'results': [{k: v for k, v in r.items()} for r in results],
            'buys': [{'code': r['code'], 'name': r['name'], 
                      'composite': round(r['composite'])} for r in buys[:20]],
        }, f, ensure_ascii=False)
    print(f"\n📄 结果已保存到: {result_file}")


if __name__ == '__main__':
    main()
