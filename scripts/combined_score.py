#!/usr/bin/env python3
"""融合评分系统 v10 — 40d×70%+20d×30% (feat_tushare特征管道)"""
import duckdb, os, json, sys, numpy as np, lightgbm as lgb
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date
from feat_tushare import (
    compute_features, get_tushare_db, load_index_data,
    get_board_index, apply_forward_adjust,
    BASE_FEAT_NAMES, N_BASE, GTJA_CODES, FEAT_WIN,
    standardize, get_factor_from_db,
)

DB_PATH = os.path.expanduser('~/.hermes/stockdb/tushare.db')
MODEL_DIR = os.path.expanduser('~/.hermes/stockdb/models')
HOLD_PATH = os.path.expanduser('~/.hermes/stockdb/holdings.json')

# 新模型（从M2拷贝）
REG20_MODEL = os.path.join(MODEL_DIR, 'lgb_reg_20d_tushare_v13_opt.txt')
REG20_STATS = os.path.join(MODEL_DIR, 'v6_norm_stats_20d_tushare_v13_opt.json')
REG40_MODEL = os.path.join(MODEL_DIR, 'lgb_reg_40d_new_stkfactor.txt')
REG40_STATS = os.path.join(MODEL_DIR, 'v6_norm_stats_40d_tushare_v2_stkfactor.json')

# 融合权重
W40 = 0.70
W20 = 0.30

# 特征选择索引（匹配训练脚本）
BASE_KEEP_INDICES = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
FACTOR_FIELDS = ['kdj_k_bfq', 'atr_bfq', 'rsi_bfq_12']
N_FACTORS = len(FACTOR_FIELDS)

# 规则评分权重
WEIGHTS = {'money_flow':0.30,'momentum':0.25,'quality':0.20,'technical':0.15,'valuation':0.10}


def s_mf(mf):
    if mf is None: return None
    m=mf/1e8
    if m>10: return 100
    if m>5: return 90
    if m>2: return 80
    if m>1: return 70
    if m>0.5: return 60
    if m>0: return 50
    if m==0: return 30
    return 10

def s_mom(c20,c60,d5):
    s=50
    if c20<-15:s+=20
    elif c20<-10:s+=15
    elif c20<-5:s+=10
    elif c20<0:s+=5
    elif c20>10:s-=15
    elif c20>5:s-=5
    if c60<-25:s+=15
    elif c60<-15:s+=10
    elif c60<-5:s+=5
    elif c60>10:s-=10
    elif c60>5:s-=5
    if d5<-5:s+=15
    elif d5<-2:s+=10
    elif d5<0:s+=5
    elif d5>5:s-=10
    elif d5>2:s-=5
    return max(0,min(100,s))

def s_qual(roe,py,ry):
    if roe is None and py is None: return None
    s=50
    if roe is not None:
        if roe>25:s+=25
        elif roe>20:s+=20
        elif roe>15:s+=15
        elif roe>10:s+=10
        elif roe>5:s+=5
        else:s-=10
    if py is not None:
        if py>50:s+=15
        elif py>30:s+=10
        elif py>10:s+=5
        elif py>0:s+=2
        elif py<-30:s-=15
        elif py<0:s-=5
    if ry is not None:
        if ry>30:s+=10
        elif ry>15:s+=5
        elif ry>0:s+=2
        elif ry<-20:s-=10
        elif ry<0:s-=5
    return max(0,min(100,s))

def s_tech(bull,d120,vr):
    s=50
    if bull:s+=25
    else:s-=5
    if d120 is not None:
        if -5<=d120<=10:s+=15
        elif 10<d120<=20:s+=5
        elif 20<d120<=35:s+=0
        elif d120>35:s-=10
        elif -15<=d120<-5:s+=5
        elif d120<-15:s-=10
    if vr is not None:
        if 1.2<=vr<=3:s+=10
        elif vr>3:s+=5
        elif vr<0.5:s-=5
    return max(0,min(100,s))

def s_val(pe,pb):
    if pe is None and pb is None: return None
    s=50
    if pe is not None and pe>0:
        if pe<15:s+=25
        elif pe<25:s+=15
        elif pe<40:s+=5
        elif pe>100:s-=15
        elif pe>50:s-=5
    elif pe is not None and pe<0:s-=10
    if pb is not None and pb>0:
        if pb<1.5:s+=15
        elif pb<3:s+=10
        elif pb<5:s+=5
        elif pb>10:s-=10
    return max(0,min(100,s))

def compute_ml_features(code, rows, conn, factor_cache, idx_data, code_full_map):
    """用 feat_tushare 管道计算29维特征（26基础 + 3因子）"""
    try:
        closes = [float(r[1]) for r in rows]   # close
        opens_raw = [float(r[2]) for r in rows]  # open
        highs_raw = [float(r[3]) for r in rows]  # high
        lows_raw = [float(r[4]) for r in rows]   # low
        pcts = [float(r[5])/100.0 for r in rows]  # change_pct → 小数
        volumes = [float(r[6]) for r in rows]    # volume
        
        # 复权因子
        code_short = code
        ts_code_full = code_full_map.get(code, code)
        adj_rows = conn.execute(
            "SELECT trade_date, adj_factor FROM adj_factor WHERE stock_code=? ORDER BY trade_date",
            [code]
        ).fetchall()
        dates_str = [str(r[0])[:10] for r in rows]
        
        # 前复权（行序：ascending）
        adj_closes, adj_highs, adj_lows = apply_forward_adjust(
            closes, highs_raw, lows_raw, adj_rows, dates_str
        )
        
        # 指数数据
        board_idx = get_board_index(code)
        idx_info = idx_data.get(board_idx)
        idx_closes = None
        if idx_info and dates_str[-1] in idx_info['dict']:
            import bisect
            ip = bisect.bisect_left(idx_info['dates'], dates_str[-1])
            if ip >= 20 and ip < len(idx_info['dates']):
                idx_closes = [idx_info['dict'][idx_info['dates'][j]] for j in range(ip + 1)]
        
        # 估值
        val_row = conn.execute(
            "SELECT pe_ttm, pb, total_mv FROM stock_valuation "
            "WHERE stock_code=? ORDER BY date DESC LIMIT 1",
            [code]
        ).fetchone()
        val_dict = {}
        if val_row:
            pe, pb, mv = val_row
            if pe and float(pe) > 0: val_dict['ep'] = 1.0 / float(pe)
            if pb and float(pb) > 0: val_dict['bp'] = 1.0 / float(pb)
            if mv and float(mv) > 0: val_dict['ln_cap'] = np.log(float(mv))
        
        # 计算30基础特征（行序：ascending，与训练一致）
        feat = compute_features(
            adj_closes, adj_highs, adj_lows, volumes, pcts,
            idx_closes, val_dict
        )
        
        # 选择26个基础特征
        feat_selected = np.array([feat[i] for i in BASE_KEEP_INDICES], dtype=np.float64)
        
        # stk_factor 因子
        factor_vals = []
        if ts_code_full in factor_cache:
            fv = factor_cache[ts_code_full]
            for f in FACTOR_FIELDS:
                factor_vals.append(float(fv.get(f, 0.0)))
        else:
            # 实时查
            dt_clean = dates_str[-1].replace('-', '')
            fv = get_factor_from_db(code, dt_clean, FACTOR_FIELDS)
            factor_vals = [float(fv.get(f, 0.0)) for f in FACTOR_FIELDS]
        
        feat_29 = np.append(feat_selected, np.array(factor_vals, dtype=np.float64))
        return feat_29, dates_str[-1]
    except Exception as e:
        return None, None


def preload_factors(conn, stock_codes):
    """预加载 stk_factor 数据到缓存"""
    cache = {}
    try:
        rows = conn.execute(f"""
            SELECT ts_code, trade_date, 
                   json_extract_string(extra, '$.kdj_k_bfq') as kdj_k_bfq,
                   json_extract_string(extra, '$.atr_bfq') as atr_bfq,
                   json_extract_string(extra, '$.rsi_bfq_12') as rsi_bfq_12
            FROM stk_factor
            WHERE trade_date >= '20260601' AND trade_date <= '20260707'
        """).fetchall()
        for row in rows:
            code, dt, kdj, atr, rsi = row
            # 只保留最新日期
            if code not in cache or dt > cache[code].get('_dt', ''):
                cache[code] = {'kdj_k_bfq': float(kdj or 0), 'atr_bfq': float(atr or 0),
                               'rsi_bfq_12': float(rsi or 0), '_dt': str(dt or '')}
        print(f"✅ stk_factor缓存: {len(cache)}只")
    except Exception as e:
        print(f"  ⚠️ stk_factor预加载失败: {e}")
    return cache


def build_code_full_map(conn):
    """构建 stock_code → ts_code 映射"""
    code_map = {}
    try:
        rows = conn.execute("SELECT DISTINCT ts_code, stock_code FROM stock_basic").fetchall()
        for ts, sc in rows:
            code_map[str(sc or '')] = str(ts or '')
    except:
        pass
    return code_map

def main():
    ref_date_str = None
    for i,a in enumerate(sys.argv):
        if a=='--date' and i+1<len(sys.argv):
            ref_date_str=sys.argv[i+1]
    today=date.fromisoformat(ref_date_str) if ref_date_str else date.today()
    today_str=today.isoformat()

    print("="*65)
    print("融合评分系统 v10 — 40d×70%+20d×30% (feat_tushare特征管道)")
    print(f"  模型: 40d={os.path.basename(REG40_MODEL)} / 20d={os.path.basename(REG20_MODEL)}")
    print("="*65)

    # ── 加载模型 ──
    reg20_model=None; reg40_model=None; stats20={}; stats40={}
    if os.path.exists(REG20_MODEL):
        reg20_model=lgb.Booster(model_file=REG20_MODEL)
        print(f"✅ 20日模型已加载 ({reg20_model.num_trees()}棵树)")
        if os.path.exists(REG20_STATS):
            with open(REG20_STATS) as f: stats20=json.load(f)
            print(f"✅ 20日norm_stats已加载 ({len(stats20)}维)")
    if os.path.exists(REG40_MODEL):
        reg40_model=lgb.Booster(model_file=REG40_MODEL)
        print(f"✅ 40日模型已加载 ({reg40_model.num_trees()}棵树)")
        if os.path.exists(REG40_STATS):
            with open(REG40_STATS) as f: stats40=json.load(f)
            print(f"✅ 40日norm_stats已加载 ({len(stats40)}维)")

    # ── 连接数据库 ──
    conn=duckdb.connect(DB_PATH, read_only=True)

    # ── 预加载指数数据 ──
    print("\n预加载指数数据...")
    idx_data = load_index_data()
    print(f"  ✅ {len(idx_data)}个指数已加载")

    # ── 预加载 stk_factor 缓存 ──
    factor_cache = preload_factors(conn, [])

    # ── 构建 code_full_map ──
    code_full_map = build_code_full_map(conn)

    # 计算市场风险评分
    risk_score=None
    try:
        idx_rows=conn.execute("SELECT close,volume FROM index_daily WHERE index_code='000001' ORDER BY date DESC LIMIT 120").fetchall()
        if len(idx_rows)>=120:
            closes=[float(r[0]) for r in idx_rows][::-1]
            vols=[float(r[1]) if r[1] else 0 for r in idx_rows][::-1]
            ma60_now=sum(closes[-60:])/60
            ma60_prev=sum(closes[-80:-20])/60 if len(closes)>=80 else ma60_now
            slope=(ma60_now/ma60_prev-1)*100
            trend_s=1.0/(1.0+np.exp(-(slope-1.0)*1.5))
            rets=[(closes[i]/closes[i-1]-1)*100 for i in range(1,len(closes))]
            vol20=np.std(rets[-20:])*np.sqrt(252) if len(rets)>=20 else 20
            vol_s=max(0,min(1,1-(vol20-15)/25))
            mv5,mv20=sum(vols[-5:])/5,sum(vols[-20:])/20
            mp5,mp20=sum(closes[-5:])/5,sum(closes[-20:])/20
            c_vr,c_pr=mv5/mv20 if mv20>0 else 1,mp5/mp20
            confirm_s=1.0 if (c_vr>1 and c_pr>1) or (c_vr<1 and c_pr<1) else 0.5
            risk_score=trend_s*0.40+vol_s*0.30+confirm_s*0.30
    except: pass

    with open(HOLD_PATH) as f: data=json.load(f)
    targets=[p for p in data['positions'] if p.get('status') in ('watch_active','watch_cold','hold') and not p['code'].startswith('TRUST')]

    results=[]
    for p in targets:
        code=p['code']; name=p['name']; status=p['status']
        date_filter=f" AND date<='{today_str}'" if ref_date_str else ""
        rows=conn.execute(f"""
            SELECT trade_date,close,open,high,low,COALESCE(pct_chg,0),vol,amount
            FROM daily WHERE ts_code LIKE '{code}%'{date_filter} ORDER BY date DESC LIMIT 120
        """).fetchall()
        if not rows or len(rows)<120: continue
        rows=rows[::-1]
        l_close=rows[-1][1]; l_date=str(rows[-1][0])
        closed=[r[1] for r in rows]
        ma60=np.mean(closed[-60:]); ma120=np.mean(closed)
        bull=np.mean(closed[-5:])>np.mean(closed[-10:])>np.mean(closed[-20:])>ma60
        dev120=(l_close/ma120-1)*100
        chg20=(l_close/closed[-20]-1)*100; chg60=(l_close/closed[-60]-1)*100
        d5_chg=(l_close/closed[-6]-1)*100
        vols=np.array([r[6] for r in rows[-20:]])
        vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1

        mf_date_filter=f" AND date<='{today_str}'" if ref_date_str else ""
        mf=conn.execute(f"SELECT COALESCE(SUM(main_net),0) FROM money_flow WHERE stock_code='{code}' AND trade_date>='20260501'{mf_date_filter}").fetchone()[0]
        # fin_income 使用 ts_code（带 .SZ/.SH 后缀）
        fin_code = code_full_map.get(code, code)
        fin=conn.execute(f"SELECT roe,profit_yoy,revenue_yoy FROM fin_income WHERE ts_code='{fin_code}' ORDER BY end_date DESC LIMIT 1").fetchone()
        val=conn.execute(f"SELECT pe_ttm,pb FROM stock_valuation WHERE stock_code='{code}' ORDER BY date DESC LIMIT 1").fetchone()

        # 规则评分
        rs=[]; rw=[]
        ms=s_mf(mf)
        if ms is not None: rs.append(ms*WEIGHTS['money_flow']); rw.append(WEIGHTS['money_flow'])
        rs.append(s_mom(chg20,chg60,d5_chg)*WEIGHTS['momentum']); rw.append(WEIGHTS['momentum'])
        qs=s_qual(fin[0] if fin else None,fin[1] if fin else None,fin[2] if fin else None)
        if qs is not None: rs.append(qs*WEIGHTS['quality']); rw.append(WEIGHTS['quality'])
        rs.append(s_tech(bull,dev120,vr)*WEIGHTS['technical']); rw.append(WEIGHTS['technical'])
        vs=s_val(val[0] if val else None,val[1] if val else None)
        if vs is not None: rs.append(vs*WEIGHTS['valuation']); rw.append(WEIGHTS['valuation'])
        rule_score=sum(rs)/sum(rw) if rw else 50

        # ML预测 — feat_tushare管道（26基础+3因子=29维）
        reg20_pred=0; reg40_pred=0
        feat_29, dt_str = compute_ml_features(code, rows, conn, factor_cache, idx_data, code_full_map)
        if feat_29 is not None:
            # 20d预测
            f20 = standardize(feat_29.reshape(1, -1), stats20)
            f20 = np.nan_to_num(f20, nan=0.0)
            if reg20_model: reg20_pred = float(reg20_model.predict(f20)[0])

            # 40d预测（用相同的29维特征，不同的norm_stats）
            f40 = standardize(feat_29.reshape(1, -1), stats40)
            f40 = np.nan_to_num(f40, nan=0.0)
            if reg40_model: reg40_pred = float(reg40_model.predict(f40)[0])
        cls_prob=0.5

        # 评分融合: 40d 70% + 20d 30%
        reg20_score = max(0, min(100, (reg20_pred + 10) / 50 * 100))
        reg40_score = max(0, min(100, (reg40_pred + 10) / 50 * 100))
        reg20_pct = reg20_pred
        reg40_pct = reg40_pred
        lstm_score = 50
        gtja_score = 50
        
        composite = reg40_score * W40 + reg20_score * W20 if reg40_model else reg20_score

        if composite>=70: conclusion="🟢 推荐"
        elif composite>=55: conclusion="🟡 关注"
        else: conclusion="⚪ 不参与"
        if dev120>35: pos="⚠️追高"
        elif dev120>20: pos="偏高" if not bull else "多头合理"
        elif dev120<-15: pos="💀破位"
        elif dev120<-5: pos="超卖"
        else: pos="合理✅"

        may_first=conn.execute(f"SELECT close FROM daily WHERE ts_code LIKE '{code}%' AND trade_date>='20260501' ORDER BY date LIMIT 1").fetchone()
        may_chg=(l_close/may_first[0]-1)*100 if may_first else 0
        results.append((composite,code,name,l_close,dev120,bull,rule_score,reg20_pred,reg20_score,conclusion,pos,may_chg,status,lstm_score,reg40_pct,reg20_pct))

    results.sort(key=lambda r: r[0], reverse=True)
    print(f"\n{'排名':>4} {'代码':6s} {'名称':8s} {'融合分':>6s} {'40d预':>7s} {'20d预':>7s} {'年线偏':>7s} {'位置':8s} {'结论':10s}")
    print(f"{'─'*78}")
    for i,r in enumerate(results,1):
        comp,code,name,price,dev,bull,rule,reg20,reg20_s,concl,pos,may,st,lstm_s,reg40,reg20_pct = r
        print(f"{i:>4} {code:6s} {name:8s} {comp:>5.0f}  {reg40:>+6.2f} {reg20_pct:>+6.2f} {dev:>+6.0f}% {pos:8s} {concl}")

    print(f"\\n{'='*65}\n📋 执行清单\n{'='*65}")
    buys=[r for r in results if r[0]>=70]
    watches=[r for r in results if 55<=r[0]<70]
    if buys:
        print(f"\n🟢 推荐 ({len(buys)}只)：")
        for r in buys: print(f"  {r[2]:8s} {r[1]:6s}  融合{r[0]:.0f}  40d={r[14]:+.2f}% 20d={r[15]:+.2f}%")
    if watches:
        print(f"\n🟡 关注 ({len(watches)}只)：")
        for r in watches: print(f"  {r[2]:8s} {r[1]:6s}  融合{r[0]:.0f}  40d={r[14]:+.2f}% 20d={r[15]:+.2f}%")
    conn.close()

    # 评分缓存（兼容旧代码）
    try:
        cache={'date':today_str,'_version':'10','scores':{}}
        for r in results:
            code=r[1]
            cache['scores'][code]={
                'fusion':round(r[0],1),
                'reg20':round(r[7],4),   # reg20_pred 原始值
                'reg40':round(r[14],4),  # reg40_pred 原始值
                'rule_score':round(r[6],1),
            }
        with open(os.path.join(os.path.expanduser('~/.hermes/stockdb'),'_score_cache.json'),'w') as f:
            json.dump(cache,f,ensure_ascii=False)
    except: pass

    print(f"\n✅ 完成（结果已保存到 _score_cache.json）")

if __name__=='__main__':
    main()
