# 目的：CMMR 权重重排对拍——现行40/40/20 vs 提议40/20/40 等若干组
# 每套权重：80+池 top10 超池均（配对NW-t）、分数段单调性、全池超额
import duckdb, sqlite3, numpy as np, pandas as pd
from scipy import stats

con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
s = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
# 日期归一：signal_history.date 混存 8位数字 与 ISO 两种格式（09-20 实锤），统一为8位；
# stock_daily.date 为 DATE 类型，查询侧一律 strftime 转8位比较
dates = sorted({str(r[0]).replace('-', '') for r in s.execute(
    "select distinct date from signal_history where cmmr_score is not null")})

idx = con.execute("select strftime(date,'%Y%m%d') d, close from index_daily where index_code='000852.SH' order by date").df()
idm = dict(zip(idx.d.astype(str), idx.close.astype(float)))
allday = con.execute("select distinct strftime(date,'%Y%m%d') d from stock_daily where date>='2026-05-01' order by 1").df()['d'].astype(str).tolist()

def get_future_close(codes, d0, fd):
    end = allday[min(allday.index(d0) + fd, len(allday) - 1)]
    q = ",".join(f"'{c}'" for c in codes)
    f = con.execute(f"select stock_code, close from (select stock_code, close, row_number() over (partition by stock_code order by date desc) rn from stock_daily where strftime(date,'%Y%m%d') between '{d0}' and '{end}' and stock_code in ({q})) where rn=1").df()
    return dict(zip(f.stock_code, f.close.astype(float)))

def factors(codes, d0):
    """复刻 signal_agent 三因子输入（生产口径）"""
    q = ",".join(f"'{c}'" for c in codes)
    df = con.execute(f"""
        select stock_code, strftime(date,'%Y%m%d') date, close, volume, open from stock_daily
        where strftime(date,'%Y%m%d') <= '{d0}' and stock_code in ({q})
        qualify row_number() over (partition by stock_code order by date desc) <= 60
    """).df()
    out = {}
    for code, g in df.groupby('stock_code'):
        g = g.sort_values('date')
        cl, vol, op = g.close.values.astype(float), g.volume.values.astype(float), g.open.values.astype(float)
        if len(cl) < 60: continue
        ma40 = cl[-40:].mean(); ma40_l20 = cl[-60:-20].mean()
        slope = (ma40 - ma40_l20) / ma40_l20 if ma40_l20 > 0 else 0
        p10 = (cl[-1] - cl[-11]) / cl[-11]
        vr = vol[-1] / (vol[-5:].mean() if vol[-5:].mean() > 0 else 1)
        out[code] = (slope, p10, vr, op[-1], cl[-1])
    return out

def score(slope, p10, vr, opn, cl_, w):
    """w=(wt趋势, wo超卖, wv量能)"""
    if slope < 0: return 0.0
    t = w[0] if slope > 0.02 else (w[0] / 2 if slope > 0 else 0)
    o = w[1] if p10 < -0.08 else (w[1] / 2 if p10 < -0.04 else 0)
    v = w[2] if (vr < 0.8 or (vr > 1.2 and cl_ > opn)) else 0
    return t + o + v

WEIGHTS = {
    '现行 40/40/20': (40, 40, 20),
    '提议 40/20/40': (40, 20, 40),
    '对照 40/0/60':  (40, 0, 60),
    '对照 20/40/40': (20, 40, 40),
}

# 逐信号日：算因子一次，各权重只换打分
import os, pickle
_cache = '/tmp/_wp_cache_0920.pkl'
day_data = []
if os.path.exists(_cache):
    day_data = pickle.load(open(_cache, 'rb'))
else:
  for d0 in dates:
    codes = [r[0] for r in s.execute(
        "select stock_code from signal_history where replace(date,'-','')=?", (d0,))]
    if len(codes) < 500: continue
    fut = get_future_close(codes, d0, 10)
    if allday.index(d0) + 10 >= len(allday): continue   # 未来10日不齐跳过
    end = allday[allday.index(d0) + 10]
    f = factors(codes, d0)
    rows = []
    for c, (sl, p10, vr, op, cl_) in f.items():
        if c not in fut: continue
        rows.append((c, sl, p10, vr, op, cl_, (fut[c] - cl_) / cl_ * 100))
    if len(rows) < 500: continue
    day_data.append((d0, idm.get(d0), pd.DataFrame(rows, columns=['code','slope','p10','vr','open','close','fwd'])))
  pickle.dump(day_data, open(_cache, 'wb'))
print(f"信号日 {len(day_data)} 天\n")

def nw_t(v, lag=10):
    v = np.asarray(v); n = len(v)
    if n < 5: return 0.0
    m = v.mean(); e = v - m
    g = np.sum([np.cov(e[lag_i:], e[:-lag_i], ddof=1)[0,1]*(1-lag_i/(lag+1)) for lag_i in range(1, lag+1)])
    return m / np.sqrt((np.var(v, ddof=1) + 2*g) / n)

print(f"{'权重方案':<14} {'池日':<5} {'池超额均值':<9} {'NW-t':<7} {'top10超池均':<9} {'配对t':<6} {'赢池胜率':<7} "
      f"{'100分段 fwd':<9} {'次高分段 fwd':<9} {'80分段 fwd':<9}")
for name, w in WEIGHTS.items():
    d_ex, d_leg, day100, day_mid, day80 = [], [], [], [], []
    for d0, i0, df in day_data:
        df = df.copy()
        df['sc'] = [score(*a, w) for a in zip(df.slope, df.p10, df.vr, df['open'], df.close)]
        pool = df[df.sc >= 80]
        if len(pool) < 10: continue
        pool = pool.sort_values(['sc', 'code'], ascending=[False, True])   # 无fusion次键，纯看该权重自身排序
        pe = pool.fwd.mean()
        d_ex.append(pe - df.fwd.median())   # 池超额 = 池均值 − 全市场中位
        d_leg.append(pe - pool.head(10).fwd.mean())          # top10 边际腿(负=好)
        # 分数段：满分/次高/门边
        full = w[0] + w[1] + w[2]
        segs = sorted(pool.sc.unique(), reverse=True)
        if len(segs) >= 3:
            day100.append(df[df.sc == segs[0]].fwd.mean())
            day_mid.append(df[df.sc == segs[1]].fwd.mean())
            day80.append(df[df.sc == segs[-1]].fwd.mean())
    legs = np.array(d_leg)
    print(f"{name:<14} {len(d_ex):<5} {np.mean(d_ex):<9.2f} {nw_t(d_ex):<7.2f} "
          f"{np.mean(legs)*-1:<9.2f} {nw_t(legs)*-1:<6.2f} {np.mean(legs<0):<7.0%} "
          f"{np.mean(day100):<9.2f} {np.mean(day_mid):<9.2f} {np.mean(day80):<9.2f}")
con.close(); s.close()
