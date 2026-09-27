"""40d v7 影子观察链（2026-09-27 起，用户拍板"直接上线+影子"）
每晚生产评分后跑：用退役旧模型对当日票重打分（新分数=生产 reg40 列），双方分数存
shadow_40d_scores；对历史已存分数日用最新日线算持有期收益 Rank IC 落 ic_shadow_40d_v7。
新分数口径 = core/scoring.py 的 predict_stock_score(feat_29+ex5 30维, v7模型)——逐字复刻，禁止自算特征。
用法: /usr/bin/python3 -B scripts/shadow_40d_v7.py [YYYYMMDD]
"""
import json, sqlite3, sys, time
import numpy as np
from pathlib import Path
from scipy import stats
import lightgbm as lgb
import duckdb

BASE = Path.home()/'.hermes/stockdb'
sys.path.insert(0, str(BASE))
from core import scoring as sc

OLD_MODEL = BASE/'models/retired_20260926/lgb_reg_40d_new_stkfactor.txt'
OLD_STATS = BASE/'models/retired_20260926/v6_norm_stats_40d_tushare_v2_stkfactor.json'
DATE = sys.argv[1] if len(sys.argv) > 1 else time.strftime('%Y%m%d')

old = lgb.Booster(model_file=str(OLD_MODEL))
old_stats = json.load(open(OLD_STATS))
sc._load_models()
conn = sqlite3.connect(BASE/'signals.db', timeout=30)
tdb_open = duckdb.connect(str(BASE/'tushare.db'), read_only=True)  # _compute_ml_features 内部查 daily/adj_factor/index_daily/daily_basic，须传 DuckDB 连接
rows = conn.execute(
    "SELECT date, stock_code, fusion_score, reg40 FROM signal_history WHERE date IN (?,?) AND reg40 IS NOT NULL AND reg40!=0",
    (DATE, f"{DATE[:4]}-{DATE[4:6]}-{DATE[6:]}")).fetchall()
print(f'{DATE} 生产分数 {len(rows)} 条', flush=True)
if len(rows) < 1000:
    print('当日无生产分数，跳过'); sys.exit(0)

pairs = []  # (score_date, code, old_score, new_score)
for sd_row, code, fus, reg40 in rows:
    sd_row = str(sd_row).replace('-','')
    f29, f38 = sc._compute_ml_features(code, tdb_open, as_of_date=DATE)
    if f29 is None or f38 is None: continue
    f30 = np.append(f29, float(f38[23]))          # 新口径 30维
    f29o = np.nan_to_num(sc._standardize(f29, old_stats), nan=0.0)
    f30n = np.nan_to_num(sc._standardize(f30, sc._stats40), nan=0.0)
    old_score = float(old.predict(f29o)[0])
    new_score = float(sc._reg40_model.predict(f30n)[0])
    if abs(new_score - float(reg40)) > 0.15:      # 与生产列偏差过大=口径漂移，报警不存
        print(f'  DRIFT {code} 列{reg40} vs 复算{new_score:.3f}', flush=True)
    pairs.append((sd_row, code, old_score, new_score))  # sd_row=生产分数原始日期(横杠版→无横杠)
conn.close(); tdb_open.close()
print(f'重打分 {len(pairs)} 只', flush=True)

def _conn30():
    import time as _t
    for a in range(6):
        try:
            c = sqlite3.connect(BASE/'signals.db', timeout=30)
            c.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            return c
        except sqlite3.OperationalError:
            if a == 5: raise
            _t.sleep(20)
db = _conn30()
db.execute("""CREATE TABLE IF NOT EXISTS shadow_40d_scores(
  score_date TEXT, code TEXT, old_score REAL, new_score REAL, PRIMARY KEY(score_date, code))""")
db.execute("""CREATE TABLE IF NOT EXISTS ic_shadow_40d_v7(
  score_date TEXT, eval_date TEXT, model TEXT, ic REAL, n INTEGER,
  PRIMARY KEY(score_date, eval_date, model))""")
db.executemany("INSERT OR REPLACE INTO shadow_40d_scores VALUES(?,?,?,?)",
               [(sd, c, o, n) for sd, c, o, n in pairs])
db.commit()

tdb = duckdb.connect(str(BASE/'tushare.db'), read_only=True)
cal = [str(r[0]) for r in tdb.execute("SELECT DISTINCT trade_date FROM daily ORDER BY 1").fetchall()]
cal_nodash = sorted({d.replace('-','') for d in cal})   # 统一无横杠口径（daily.trade_date 历史混格式，横杠版排序会错乱）
last = cal_nodash[-1]
# 统一无横杠口径（signal_history.date 历史行存在 YYYYMMDD 格式）
dset = sorted({str(r[0]).replace('-','') for r in db.execute("SELECT DISTINCT score_date FROM shadow_40d_scores").fetchall()})
# T+1 收益（v7 观察期短，用次日口径快出结论）；T+1 未到的日跳过，且已算过IC的成熟日不重复算（省每晚重跑）
evals = {d: cal_nodash[cal_nodash.index(d)+1] for d in dset if d in cal_nodash and cal_nodash.index(d)+1 < len(cal_nodash)}
done_ic = {r[0] for r in db.execute("SELECT DISTINCT score_date FROM ic_shadow_40d_v7").fetchall()}
for sd in dset:
    ed = evals.get(sd)
    if ed is None or sd in done_ic: continue
    sdash = f"{sd[:4]}-{sd[4:6]}-{sd[6:]}"
    sc_rows = db.execute("SELECT code, old_score, new_score FROM shadow_40d_scores WHERE score_date IN (?,?)", (sd, sdash)).fetchall()
    codes = [f"{r[0]}.SH" if r[0].startswith(('6','68','9')) else f"{r[0]}.SZ" for r in sc_rows]
    ph = ','.join('?'*len(codes))
    px = tdb.execute(f"SELECT ts_code, close FROM daily WHERE ts_code IN ({ph}) AND (trade_date=? OR trade_date=?)", codes + [ed, f"{ed[:4]}-{ed[4:6]}-{ed[6:]}"]).fetchall()
    pmap = dict((r[0].split('.')[0], float(r[1])) for r in px)
    arr = [(o, n, pmap[c]) for c, o, n in sc_rows if c in pmap]
    if len(arr) < 500: continue
    o_arr = np.array([r[0] for r in arr]); n_arr = np.array([r[1] for r in arr]); y = np.array([r[2] for r in arr])
    db.execute("INSERT OR REPLACE INTO ic_shadow_40d_v7 VALUES(?,?,?,?,?)", (sd, ed, 'old_v6', float(stats.spearmanr(o_arr, y)[0]), len(arr)))
    db.execute("INSERT OR REPLACE INTO ic_shadow_40d_v7 VALUES(?,?,?,?,?)", (sd, ed, 'new_v7', float(stats.spearmanr(n_arr, y)[0]), len(arr)))
# 4. 对拍报告（与 shadow_fusion_442_daily.py 同标准: 逐日配对差 NW-t>=2 且均值>0 才判换产）
dfr = db.execute("SELECT score_date, model, ic FROM ic_shadow_40d_v7").fetchall()
by = {}
for d_, m_, ic_ in dfr:
    by.setdefault(d_, {})[m_] = ic_
both = sorted([(d_, v['new_v7'], v['old_v6']) for d_, v in by.items() if 'new_v7' in v and 'old_v6' in v])
if both:
    v7 = np.array([x[1] for x in both]); old_ = np.array([x[2] for x in both])
    dif = v7 - old_
    n = len(dif); m = dif.mean()
    g, nwv = 5, dif.std()**2/n
    for l in range(1, g+1):
        nwv += 2*(1-l/(g+1))*(dif[:-l]-m)*(dif[l:]-m).mean()/n
    t_ = m/np.sqrt(nwv) if nwv > 0 else 0.0
    print(f"对拍{n}天: v7日均IC {v7.mean():+.4f} vs 旧 {old_.mean():+.4f} 差 {m:+.4f} NW-t={t_:.2f} v7胜天{(dif>0).mean()*100:.0f}%")
    verdict = "✅ 达到换产标准" if (n >= 30 and t_ >= 2 and m > 0) else ("❌ 判负(建议回滚退役件)" if (n >= 30 and t_ <= -2) else "样本累积中")
    print(f"判定({n}天): {verdict}")
tdb.close(); db.close()
