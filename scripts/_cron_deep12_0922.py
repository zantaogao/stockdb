#!/usr/bin/env python3
# 0922 复盘补数：日线形态 + 昨判断对账数据 + 板块归属
import duckdb, os, sqlite3
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
t = duckdb.connect('tushare.db', read_only=True)

def prof(code6):
    suf = '.SH' if code6.startswith(('6','9')) else '.SZ'
    rows = t.execute(f"SELECT trade_date,open,high,low,close,pct_chg,amount FROM daily WHERE ts_code='{code6}{suf}' AND trade_date>='20260815' ORDER BY trade_date").fetchall()
    if not rows: return f"{code6}: NO DATA"
    closes = [r[4] for r in rows]
    last = rows[-1]
    h20 = max(r[2] for r in rows[-20:]); l20 = min(r[3] for r in rows[-20:])
    h_all = max(r[2] for r in rows); l_all = min(r[3] for r in rows)
    r5 = (closes[-1]/closes[-6]-1)*100 if len(closes)>=6 else None
    ma20 = sum(closes[-20:])/min(20,len(closes))
    vols = [r[6] for r in rows]
    v5 = sum(vols[-6:-1])/5
    vratio = vols[-1]/v5 if v5 else None
    # 连涨跌天数
    streak=0
    for r in reversed(rows):
        if streak==0: streak = 1 if r[5]>0 else -1
        elif streak>0 and r[5]>0: streak+=1
        elif streak<0 and r[5]<0: streak-=1
        else: break
    # 最近跳空
    gap=''
    for i in range(max(1,len(rows)-10), len(rows)):
        if rows[i][1] > rows[i-1][2]: gap += f" {rows[i][0]}向上跳空"
        elif rows[i][1] < rows[i-1][3]: gap += f" {rows[i][0]}向下跳空"
    d10 = [(r[0][4:],round(r[5],1)) for r in rows[-10:]]
    return (f"{code6} 收{last[4]}({last[5]:+.1f}%) 5日{r5:+.1f}% 连{'涨' if streak>0 else '跌'}{abs(streak)} "
            f"量比{vratio:.1f} MA20偏离{(closes[-1]/ma20-1)*100:+.1f}% 距20高{(closes[-1]/h20-1)*100:+.1f}% "
            f"距20低{(closes[-1]/l20-1)*100:+.1f}% 区间高{h_all}低{l_all}{gap} | 近10日:{d10}")

codes = ['688191','301575','301110','001332','605598','600076','301093','301590','301237','603811','002454','688093',
         '000532','000029','000568','000608','000656','000509','000595','000031',
         '002823','600960','603177','002126','300991','603926']
print("===== 日线形态（0922） =====")
for c in codes:
    print(prof(c))

print("\n===== 板块归属对照（主账户 vs CMMR榜） =====")
for c in ['002454','601615','002823','600960','603177','002126','300991','603926','688191','301093','301575','301110']:
    suf = '.SH' if c.startswith('6') else '.SZ'
    r = t.execute(f"SELECT industry,name FROM stock_basic WHERE ts_code='{c}{suf}'").fetchone()
    print(c, r)

print("\n===== 0922 全市场宽度（复算） =====")
r = t.execute("SELECT COUNT(*) FILTER (WHERE pct_chg>0), COUNT(*) FILTER (WHERE pct_chg<0), COUNT(*), SUM(amount)/1e8 FROM daily WHERE trade_date='20260922'").fetchone()
print("0922 涨/跌/总/成交额亿:", r)
r = t.execute("SELECT COUNT(*) FILTER (WHERE pct_chg>0), COUNT(*) FILTER (WHERE pct_chg<0), COUNT(*), SUM(amount)/1e8 FROM daily WHERE trade_date='20260921'").fetchone()
print("0921 涨/跌/总/成交额亿:", r)

print("\n===== 指数 0918-0922 close+amount(亿) =====")
for r in t.execute("SELECT ts_code,trade_date,close,pct_chg,amount/1e8 FROM index_daily_raw WHERE ts_code IN ('000852.SH','000001.SH','000016.SH') AND trade_date>='20260918' ORDER BY ts_code,trade_date").fetchall():
    print(r)

print("\n===== 康欣/青木 关键日明细 =====")
for c in ['600076','301110']:
    suf = '.SH' if c.startswith('6') else '.SZ'
    for r in t.execute(f"SELECT trade_date,open,close,pct_chg FROM daily WHERE ts_code='{c}{suf}' AND trade_date>='20260918' ORDER BY trade_date").fetchall():
        print(r)
