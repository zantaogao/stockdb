"""跨族实验：Ridge(线性族) vs LightGBM(树族) vs 融合
样本: 随机300只票×近1.5年, 口径同v4管线(feat_tushare 31维, y=T+10)
切分: 按日期前80%训/后20%验
输出: 各族验证段日均截面RankIC、两族预测逐票相关性、0.5/0.5融合IC
"""
import sys, os, time, random
import numpy as np
from pathlib import Path
from scipy import stats
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

BASE = Path(os.path.expanduser('~/.hermes/stockdb'))
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / 'scripts'))
from core.db import get_tushare_db
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data

FEAT_WIN, FWD_DAYS = 60, 10
PV = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]

random.seed(42)
conn = get_tushare_db()
stocks = [r[0] for r in conn.execute("SELECT symbol FROM stock_basic WHERE market != '北交所' AND name NOT LIKE '%ST%' AND name NOT LIKE '%退%'").fetchall()]
stocks = [s for s in stocks if not s.startswith(('8','4','92'))]
sample = random.sample(stocks, 300)
idx_data = load_index_data()

rows, ys, dates, codes = [], [], [], []
t0 = time.time()
for code in sample:
    ts = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    d = conn.execute(f"SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol FROM daily WHERE ts_code='{ts}' AND trade_date>='20240601' ORDER BY trade_date").fetchall()
    if len(d) < FEAT_WIN + FWD_DAYS + 30: continue
    cl=[float(r[1]) for r in d]; hi=[float(r[2]) for r in d]; lo=[float(r[3]) for r in d]
    pc=[float(r[4])/100 for r in d]; vo=[float(r[5]) for r in d]
    dts=[str(r[0])[:10] if '-' in str(r[0]) else f'{str(r[0])[:4]}-{str(r[0])[4:6]}-{str(r[0])[6:8]}' for r in d]
    adj = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",[ts]).fetchall()
    ac,ah,al = apply_forward_adjust(cl,hi,lo,adj)
    ii = idx_data.get(get_board_index(code))
    for i in range(FEAT_WIN, len(d)-FWD_DAYS):
        idxd = {k:v for k,v in ii['dict'].items() if k<=dts[i]} if ii else None
        f = compute_features(ac[i-FEAT_WIN:i+1],ah[i-FEAT_WIN:i+1],al[i-FEAT_WIN:i+1],vo[i-FEAT_WIN:i+1],pc[i-FEAT_WIN:i+1],idxd,{'ep':0.5,'bp':0.5,'ln_cap':22.0})
        if f is None: continue
        rows.append([f[j] for j in PV]); ys.append(ac[i+FWD_DAYS]/ac[i]-1); dates.append(dts[i]); codes.append(code)
conn.close()
X = np.nan_to_num(np.array(rows, dtype=np.float64), nan=0.0)
y = np.array(ys); dt = np.array(dates)
print(f'样本 {len(X):,} 耗时{time.time()-t0:.0f}s', flush=True)

uds = np.sort(np.unique(dt)); split = uds[int(len(uds)*0.8)]
tr = dt < split; va = dt >= split

# 标准化 stats 只用训练段
sc = StandardScaler().fit(X[tr])
Xn = sc.transform(X)
params = {'objective':'regression','metric':'l2','num_leaves':15,'learning_rate':0.008,
 'feature_fraction':0.6,'bagging_fraction':0.6,'bagging_freq':5,'min_data_in_leaf':300,
 'lambda_l1':0.5,'lambda_l2':2.0,'max_depth':5,'min_gain_to_split':0.2,'verbose':-1,'num_threads':4}
m_lgb = lgb.train(params, lgb.Dataset(Xn[tr], y[tr]), num_boost_round=800,
        valid_sets=[lgb.Dataset(Xn[va], y[va])], callbacks=[lgb.early_stopping(50, verbose=False)])
p_lgb = m_lgb.predict(Xn[va])
m_rid = Ridge(alpha=10.0).fit(Xn[tr], y[tr])
p_rid = m_rid.predict(Xn[va])

va_dt = dt[va]
def daily_ic(p):
    out=[]
    for d_ in np.unique(va_dt):
        m = va_dt==d_
        if m.sum()>=100: out.append(stats.spearmanr(p[m], y[va][m])[0])
    return np.array(out)
ic_lgb, ic_rid = daily_ic(p_lgb), daily_ic(p_rid)
blend = 0.5*stats.rankdata(p_lgb)/len(p_lgb) + 0.5*stats.rankdata(p_rid)/len(p_rid)
# 融合按日算
ic_bl=[]
for d_ in np.unique(va_dt):
    m = va_dt==d_
    if m.sum()>=100:
        b = 0.5*stats.rankdata(p_lgb[m])/m.sum() + 0.5*stats.rankdata(p_rid[m])/m.sum()
        ic_bl.append(stats.spearmanr(b, y[va][m])[0])
ic_bl = np.array(ic_bl)
corr = stats.spearmanr(p_lgb, p_rid)[0]
print(f'验证天数: {len(ic_lgb)}')
print(f'LGBM  日均IC: {ic_lgb.mean():+.4f}')
print(f'Ridge 日均IC: {ic_rid.mean():+.4f}')
print(f'融合  日均IC: {ic_bl.mean():+.4f}')
print(f'两族预测 截面相关: {corr:.4f}')
t = stats.ttest_1samp(ic_bl - ic_lgb, 0)
print(f'融合−LGBM 配对t: t={t.statistic:+.2f} p={t.pvalue:.4f}')