import sqlite3, statistics, duckdb

sig = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)

# 1. 哨兵IC日历斜率（最近20个信号日）
rows = sig.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()
rows.reverse()
import datetime
def slope(ys):
    n=len(ys); xs=list(range(n))
    mx=sum(xs)/n; my=sum(ys)/n
    num=sum((x-mx)*(y-my) for x,y in zip(xs,ys)); den=sum((x-mx)**2 for x in xs)
    return num/den
print('=== 哨兵IC斜率(近20信号日, 单位/日) ===')
for i,name in [(1,'fusion'),(2,'reg10'),(3,'reg20'),(4,'reg40')]:
    ys=[r[i] for r in rows]
    half=10
    print(name, '斜率=', round(slope(ys),4), '前半均值=', round(statistics.mean(ys[:half]),4), '后半均值=', round(statistics.mean(ys[half:]),4))

# 2. 市场环境对照：同期全市场日均涨幅+涨占比
ts = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
dates = [r[0].replace('-','') for r in rows]
print('=== 市场环境对照（与哨兵IC同窗口逐日）===')
prev = None
mkt = []
for d in dates:
    if prev:
        r = ts.execute("SELECT AVG(pct_chg), SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END)*1.0/COUNT(*) FROM daily WHERE trade_date=?", (d,)).fetchone()
        mkt.append((d, r[0], r[1]))
    prev = d
for d,avg,up in mkt: print(d, '均涨=', round(avg,2) if avg is not None else None, '涨占比=', round(up*100,1) if up is not None else None)
if mkt:
    print('窗口市场日均=', round(statistics.mean([m[1] for m in mkt if m[1] is not None]),3),
          '平均涨占比=', round(statistics.mean([m[2]*100 for m in mkt if m[2] is not None]),1))

# 3. 真窗口IC近况
print('=== ic_window 近8行(真窗口) ===')
for r in sig.execute("SELECT signal_date, ic_reg10_w10, ic_fusion_w10, ic_3f_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_center_w10, ic_dual_w10, fwd10_top FROM ic_window ORDER BY signal_date DESC LIMIT 8"):
    print(r)
w = sig.execute("SELECT ic_reg10_w10, ic_fusion_w10, ic_dual_w10, ic_center_w10 FROM ic_window ORDER BY signal_date DESC LIMIT 10").fetchall()
for i,name in enumerate(['reg10_w10','fusion_w10','dual_w10','center_w10']):
    v=[r[i] for r in w if r[i] is not None]
    if v: print(name, 'n=',len(v), '均值=', round(statistics.mean(v),4), '正=', sum(1 for x in v if x>0),'/',len(v))
