# 步骤2.5 持仓与映射票二次核验 2026-09-22
import sqlite3, duckdb

led = sqlite3.connect('ledger.db')
hold = led.execute("SELECT code,name,avg_cost,shares,latest_price,stop_loss,buy_date FROM holdings WHERE status='holding' OR status=1 OR status IS NULL").fetchall()
# fallback if status filter drops all
if not hold:
    hold = led.execute("SELECT code,name,avg_cost,shares,latest_price,stop_loss,buy_date FROM holdings").fetchall()

# 榜内拟点名票（三模型融合Top10 + 10d独立Top10 中与隔夜映射相关的）
watch = {
    '600076':'康欣新材','301590':'优优绿能','300881':'盛德鑫泰','688377':'迪威尔',
    '603585':'苏利股份','300970':'华绿生物','300651':'金陵体育','001216':'华瓷股份',
    '600825':'新华传媒','301237':'和顺科技','688191':'智洋创新','002463':'沪电股份',
    '300846':'首都在线','603220':'中贝通信','688503':'聚和材料','002491':'通鼎互联',
}

db = duckdb.connect('tushare.db', read_only=True)
import datetime
# 最近120自然日内的日线
start = '20260808'
def suf(c):
    return c + ('.SH' if c.startswith(('6','9','5')) else '.SZ')
codes = sorted(set([h[0] for h in hold] + list(watch.keys())))
inlist = ",".join("'"+suf(c)+"'" for c in codes)
rows = db.execute(f"""
  SELECT ts_code, trade_date, open, high, low, close, pct_chg
  FROM daily WHERE ts_code IN ({inlist}) AND trade_date >= '{start}'
  ORDER BY ts_code, trade_date
""").fetchall()

from collections import defaultdict
series = defaultdict(list)
for r in rows:
    series[r[0][:6]].append(r)

def analyze(code, name):
    s = series.get(code, [])
    if len(s) < 6:
        return f"{code} {name}: 日线不足 未获取"
    closes = [x[5] for x in s]
    highs  = [x[3] for x in s]
    dates  = [x[1] for x in s]
    last = closes[-1]
    c5 = (last/closes[-6]-1)*100 if len(closes)>=6 else None
    c3 = (last/closes[-4]-1)*100 if len(closes)>=4 else None
    hi20 = max(highs[-20:]) if len(highs)>=20 else max(highs)
    dist_hi = (hi20/last-1)*100  # 距20日新高还差多少%
    # 连涨天数（从最后一天往前数 pct_chg>0）
    up = 0
    for x in reversed(s):
        if x[6] is not None and x[6] > 0: up += 1
        else: break
    # 5日中上涨天数
    up5 = sum(1 for x in s[-5:] if x[6] and x[6]>0)
    return (f"{code} {name} [{dates[-1]}] 收{last:.2f} | 5日{c5:+.1f}% | 3日{c3:+.1f}% | "
            f"距20日新高 {dist_hi:+.1f}% | 连涨{up}日 | 5日中{up5}天涨")

print("== 主账户/策略持仓 日线核验 ==")
for h in hold:
    print(analyze(h[0], h[1]), f"| 成本{h[2]} 现价{h[4]} 止损{h[5]}")
print("\n== 榜内关注票 ==")
for c,n in watch.items():
    print(analyze(c, n))
