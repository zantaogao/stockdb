"""分类 vs 回归 同族对拍（同一份样本、同参数、同切分）
A: regression (v3/v4 现行口径)
B: binary 分类 y=1{10d收益>0}, 用 predict_proba 排序
指标: 验证段日均截面RankIC、分类AUC、top-decile捕获收益、两者预测相关
样本: 随机300票×2024-06起, feat_tushare 31维, y=T+10
"""
import sys, os, time, random
import numpy as np
from pathlib import Path
from scipy import stats
from sklearn.metrics import roc_auc_score
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
rows, ys, dates = [], [], []
for code in sample:
    ts = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    d = conn.execute(f"SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol FROM daily WHERE ts_code='{ts}' AND trade_date>='20240601' ORDER BY trade_date").fetchall()
    if len(d) < FEAT_WIN + FWD_DAYS + 30: continue
    cl=[float(r[1]) for r in d]; hi=[float(r[2]) for r in d]; lo=[float(r[3]) for r in d]
    pc=[float(r[4])/100 for r in d]; vo=[float(r[5]) for r in d]
    dts=[str(r[0]) if len(str(r[0]))==8 else str(r[0])[:10] for r in d]
    adj = conn.execute("SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",[ts]).fetchall()
    ac,ah,al = apply_forward_adjust(cl,hi,lo,adj)
    ii = idx_data.get(get_board_index(code))
    for i in range(FEAT_WIN, len(d)-FWD_DAYS):
        idxd = {k:v for k,v in ii['dict'].items() if k<=dts[i]} if ii else None
        f = compute_features(ac[i-FEAT_WIN:i+1],ah[i-FEAT_WIN:i+1],al[i-FEAT_WIN:i+1],vo[i-FEAT_WIN:i+1],pc[i-FEAT_WIN:i+1],idxd,{'ep':0.5,'bp':0.5,'ln_cap':22.0})
        if f is None: continue
        rows.append([f[j] for j in PV]); ys.append(ac[i+FWD_DAYS]/ac[i]-1); dates.append(dts[i])
conn.close()
X = np.nan_to_num(np.array(rows, dtype=np.float64), nan=0.0); y = np.array(ys); dt = np.array(dates)
uds = np.sort(np.unique(dt)); split = uds[int(len(uds)*0.8)]
tr, va = dt < split, dt >= split
lo_, hi_ = np.percentile(X[tr], 1, axis=0), np.percentile(X[tr], 99, axis=0)
mu, sd = X[tr].mean(0), X[tr].std(0)
Xn = np.clip(X, lo_, hi_); Xn = (Xn - mu) / sd; Xn = np.nan_to_num(Xn, nan=0.0)
print(f'样本 {len(X):,}  训练 {tr.sum():,} / 验证 {va.sum():,}', flush=True)

base = {'num_leaves':15,'learning_rate':0.008,'feature_fraction':0.6,'bagging_fraction':0.6,
 'bagging_freq':5,'min_data_in_leaf':300,'lambda_l1':0.5,'lambda_l2':2.0,'max_depth':5,
 'min_gain_to_split':0.2,'verbose':-1,'num_threads':4}
m_reg = lgb.train(dict(base, objective='regression', metric='l2'), lgb.Dataset(Xn[tr], y[tr]),
 num_boost_round=800, valid_sets=[lgb.Dataset(Xn[va], y[va])], callbacks=[lgb.early_stopping(50, verbose=False)])
m_cls = lgb.train(dict(base, objective='binary', metric='auc'), lgb.Dataset(Xn[tr], (y[tr]>0).astype(int)),
 num_boost_round=800, valid_sets=[lgb.Dataset(Xn[va], (y[va]>0).astype(int))], callbacks=[lgb.early_stopping(50, verbose=False)])
p_reg = m_reg.predict(Xn[va]); p_cls = m_cls.predict(Xn[va])
va_dt, va_y = dt[va], y[va]
def daily_ic(p):
    return np.array([stats.spearmanr(p[va_dt==d], va_y[va_dt==d])[0] for d in np.unique(va_dt) if (va_dt==d).sum()>=100])
ic_reg, ic_cls = daily_ic(p_reg), daily_ic(p_cls)
auc = roc_auc_score((va_y>0).astype(int), p_cls)
# top-decile 捕获: 每日按两族分数取前10%票的实际平均10d收益
cap_reg, cap_cls = [], []
for d in np.unique(va_dt):
    m = va_dt==d
    if m.sum()<200: continue
    k = m.sum()//10
    pr_, pc_, yy = p_reg[m], p_cls[m], va_y[m]
    cap_reg.append(yy[np.argsort(pr_)[-k:]].mean()); cap_cls.append(yy[np.argsort(pc_)[-k:]].mean())
t = stats.ttest_1samp(ic_reg - ic_cls, 0)
print(f'回归  日均RankIC: {ic_reg.mean():+.4f}')
print(f'分类  日均RankIC: {ic_cls.mean():+.4f}   (分类AUC={auc:.4f})')
print(f'配对t(回归−分类): t={t.statistic:+.2f} p={t.pvalue:.4f}')
print(f'每日前10%票 实际10d收益: 回归选 {np.mean(cap_reg)*100:+.3f}%  分类选 {np.mean(cap_cls)*100:+.3f}%')
print(f'两族分数截面相关: {stats.spearmanr(p_reg, p_cls)[0]:.4f}')