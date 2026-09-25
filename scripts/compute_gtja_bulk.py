#!/usr/bin/env python3
"""
批量计算GTJA因子全期数据 — 保存到factor_daily_values
然后重训LightGBM模型(31→70维)

用法: python3 compute_gtja_bulk.py
"""
import os, sys, time, importlib, tempfile, json
import duckdb, numpy as np, pandas as pd
from pathlib import Path

HOME = os.path.expanduser('~')
DB = os.path.join(HOME, '.hermes/stockdb/stock.db')

# 39个GTJA因子
GTJA_FACTORS = [
    ('gtja_150_inv', 150, True), ('gtja_158_inv', 158, True), ('gtja_159_inv', 159, True),
    ('gtja_167_inv', 167, True), ('gtja_175_inv', 175, True), ('gtja_187_inv', 187, True),
    ('gtja_184', 184, False), ('gtja_168', 168, False), ('gtja_189_inv', 189, True),
    ('gtja_147_inv', 147, True), ('gtja_151_inv', 151, True), ('gtja_145_inv', 145, True),
    ('gtja_161_inv', 161, True), ('gtja_177', 177, False), ('gtja_157', 157, False),
    ('gtja_144', 144, False), ('gtja_156', 156, False), ('gtja_185', 185, False),
    ('gtja_179_inv', 179, True), ('gtja_140', 140, False), ('gtja_042', 42, False),
    ('gtja_046', 46, False), ('gtja_083', 83, False), ('gtja_099', 99, False),
    ('gtja_041', 41, False), ('gtja_062', 62, False), ('gtja_034', 34, False),
    ('gtja_025', 25, False), ('gtja_016', 16, False), ('gtja_005', 5, False),
    ('gtja_049', 49, False), ('gtja_048', 48, False), ('gtja_032', 32, False),
    ('gtja_026', 26, False), ('gtja_008', 8, False), ('gtja_035', 35, False),
    ('gtja_038', 38, False), ('gtja_001', 1, False), ('gtja_006', 6, False),
]

def build_panel_full():
    """构建全期581天panel（同bench脚本）"""
    con = duckdb.connect(DB)
    df = con.execute("""
        SELECT stock_code, date, open, close, high, low, volume, amount,
               change_pct/100.0 as returns
        FROM stock_daily WHERE date >= '2024-01-01' ORDER BY date, stock_code
    """).fetchdf()
    con.close()
    
    panel = {}
    for col in ['open','close','high','low','volume','amount','returns']:
        panel[col] = df.pivot_table(index='date', columns='stock_code', values=col)
    panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)
    # 未来5日收益（标签）
    panel['ret_future'] = panel['close'].pct_change(5).shift(-5)
    return panel


def compute_all_gtja(panel):
    """计算所有39个GTJA因子，返回dict{factor_name: DataFrame(日期×股票)}"""
    results = {}
    t0 = time.time()
    
    for fname, alpha_num, invert in GTJA_FACTORS:
        alpha_id = f"alpha_{alpha_num:03d}"
        t1 = time.time()
        try:
            mod = importlib.import_module(f"src.factors.zoo.gtja191.{alpha_id}")
            signal = mod.compute(panel)
        except Exception as e:
            print(f"  [{fname:15s}] ❌ {str(e)[:50]}", flush=True)
            continue
        
        if signal is None or signal.empty:
            continue
        
        if invert:
            signal = -signal
        
        results[fname] = signal
        print(f"  [{fname:15s}] {signal.shape} ({time.time()-t1:.1f}s)", flush=True)
    
    print(f"  完成: {len(results)}/{len(GTJA_FACTORS)}个因子, {time.time()-t0:.0f}s", flush=True)
    return results


def save_to_factor_db(con, results, panel):
    """将因子值保存到factor_daily_values（CSV→COPY批量导入）"""
    csv_path = os.path.join(tempfile.gettempdir(), 'gtja_bulk.csv')
    lines = []
    total = 0
    
    for fname, signal in results.items():
        for dt in signal.index:
            date_str = str(dt)[:10]
            row = signal.loc[dt].dropna()
            for code, val in row.items():
                if pd.isna(val): continue
                lines.append(f"{date_str}|{code}|{fname}|{val}\n")
                total += 1
    
    print(f"  写入CSV: {total:,}条...", flush=True)
    with open(csv_path, 'w') as f:
        f.writelines(lines)
    
    # 先清空
    con.execute("DELETE FROM factor_daily_values WHERE factor_name IN ({})".format(
        ','.join([f"'{n}'" for n, _, _ in GTJA_FACTORS])))
    
    # COPY导入
    con.execute(f"""
        COPY factor_daily_values (date, stock_code, factor_name, raw_value)
        FROM '{csv_path}' (DELIMITER '|', AUTO_DETECT FALSE)
    """)
    print(f"  COPY完成: {total:,}条", flush=True)


def save_training_data(panel, gtja_results):
    """生成训练用特征矩阵（原有31维 + 39个GTJA因子 = 70维）"""
    print("\n生成训练特征矩阵...", flush=True)
    
    # 已有特征（从stock_daily计算）
    con = duckdb.connect(DB)
    daily = con.execute("""
        SELECT stock_code, date, close, change_pct/100.0 as ret, amount
        FROM stock_daily WHERE date >= '2023-11-01' ORDER BY stock_code, date
    """).fetchdf()
    val_df = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation").fetchdf()
    con.close()
    
    vd = {}
    for _, r in val_df.iterrows():
        k=(r['stock_code'],str(r['date'])[:10])
        ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
        bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None
        lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
        if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}
    
    rows = []; meta = []
    for code, grp in daily.groupby('stock_code', sort=False):
        n=len(grp); c_arr=grp['close'].values.astype(np.float64)
        r_arr=grp['ret'].values.astype(np.float64); a_arr=grp['amount'].values.astype(np.float64)
        d_arr=grp['date'].values
        if n<120: continue
        for i in range(119, n):
            c=c_arr[:i+1]; lc=c[-1]
            chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1
            chg60=lc/c[-60]-1; chg120=lc/c[0]-1
            ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:]); ma120=np.mean(c)
            d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/ma120-1
            b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
            rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
            std20=np.std(c[-20:])/np.mean(c[-20:])*100
            vols=a_arr[:i+1][-20:]; vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
            rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
            nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
            c1d=r_arr[i] if i>0 else 0; c3d=lc/c[-3]-1 if len(c)>=3 else 0
            v=vd.get((code,str(d_arr[i])[:10]),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); lc2=v.get('ln_cap',22)
            rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
            
            # GTJA因子（从计算结果中提取）
            dt_str = str(d_arr[i])[:10]
            gtja_vals = []
            for fname in gtja_results:
                sig = gtja_results[fname]
                if dt_str in sig.index and code in sig.columns:
                    val = sig.loc[dt_str, code]
                    gtja_vals.append(val if not pd.isna(val) else 0.0)
                else:
                    gtja_vals.append(0.0)
            
            feat = np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
                b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,
                ep,bp,lc2] + gtja_vals, dtype=np.float32)
            rows.append(feat)
            meta.append({'date':str(d_arr[i])[:10],'code':code,'rf':rf})
    
    arr = np.array(rows); labels = np.array([m['rf'] for m in meta])
    np.savez(f"{HOME}/.hermes/stockdb/train_data_70d.npz",
             X=arr, y=labels, meta=np.array([json.dumps(m) for m in meta]))
    print(f"  训练特征矩阵: {arr.shape} ({len(meta)}样本)", flush=True)
    return arr, labels, meta


if __name__ == '__main__':
    print("GTJA因子全量计算 + 训练特征生成", flush=True)
    
    # 1. 构建panel
    print("构建panel...", flush=True)
    panel = build_panel_full()
    print(f"  Panel: {panel['close'].shape}", flush=True)
    
    # 2. 计算因子
    gtja_results = compute_all_gtja(panel)
    
    # 3. 生成训练特征矩阵（跳过DB保存，直接内存→npz）
    print("\n生成训练特征矩阵...", flush=True)
    save_training_data(panel, gtja_results)
    
    print(f"\n✅ 完成! 特征从31维扩展到{31+len(gtja_results)}维 ({len(gtja_results)}个GTJA因子)")
    print("  PC上运行: python3 pc_final_train_v4.py 来重训模型")
