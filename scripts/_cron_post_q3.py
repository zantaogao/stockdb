#!/usr/bin/env python3
"""日线深复盘：主账户持仓 + 六榜 top10 + 板块龙头，近30交易日"""
import duckdb, os
BASE = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{BASE}/tushare.db', read_only=True)

CODES = {
 # 主账户持仓
 '301093.SZ','002454.SZ','301283.SZ','300658.SZ','688093.SH','001332.SZ','603585.SH','301237.SZ',
 '601615.SH','300854.SZ','688186.SH','603811.SH','603966.SH','603202.SH','600076.SH','300651.SZ','301575.SZ',
 # 三模型融合 top10
 '002961.SZ','600363.SH','001225.SZ','603823.SH','688117.SH','002545.SZ','688629.SH','603890.SH','600499.SH','002253.SZ',
 # CMMR独立 top10
 '000428.SZ','000430.SZ','000505.SZ','000523.SZ','000533.SZ','000550.SZ','000636.SZ','000668.SZ','000713.SZ','000721.SZ',
 # CMMR+三模型 top10
 '600547.SH','688011.SH','300621.SZ','603900.SH','301098.SZ','688031.SH','300387.SZ','300535.SZ',
 # 10d独立 top10 (dupes: 603823 002961 688117 600547 301575)
 '601238.SH','605303.SH','600857.SH','300803.SZ','603226.SH',
 # 中枢版 top10
 '300066.SZ','300381.SZ','688133.SH','002354.SZ','603956.SH','300725.SZ','301687.SZ','301533.SZ','600903.SH',
 # 中枢版+三模型 top10
 '300640.SZ','688737.SH','002554.SZ','603488.SH','600955.SH','603077.SH',
 # 板块龙头抽查
 '000002.SZ','600048.SH','002244.SZ','688981.SH','603986.SH','688012.SH','002049.SZ',
}
ph = ','.join(["?"]*len(CODES))
rows = t.execute(f"""
    SELECT ts_code, trade_date, open, high, low, close, pct_chg, vol, amount
    FROM daily WHERE ts_code IN ({ph}) AND trade_date >= '20260801'
    ORDER BY ts_code, trade_date""", sorted(CODES)).fetchall()
from collections import defaultdict
series = defaultdict(list)
for r in rows: series[r[0]].append(r)
names = {r[0]: r[1] for r in t.execute("SELECT ts_code, name FROM stock_basic").fetchall()}
out = open('/tmp/daily_deep.txt','w')
for code in sorted(CODES):
    s = series.get(code, [])
    if not s:
        out.write(f"### {code} {names.get(code,'?')} NO DATA\n"); continue
    s = s[-30:]
    closes = [x[5] for x in s]; highs = [x[3] for x in s]; lows=[x[4] for x in s]; vols=[x[7] for x in s]; pcts=[x[6] for x in s]
    hi20 = max(highs[-20:]); lo20 = min(lows[-20:])
    hi_all = max(highs); lo_all = min(lows)
    ma5 = sum(closes[-5:])/5; ma10 = sum(closes[-10:])/10; ma20 = sum(closes[-20:])/20
    last = s[-1]
    # consecutive up/down days ending today
    streak = 0
    for p in reversed(pcts):
        if streak == 0: streak = 1 if p > 0 else -1
        elif streak > 0 and p > 0: streak += 1
        elif streak < 0 and p < 0: streak -= 1
        else: break
    vol5 = sum(vols[-6:-1])/5 if len(vols)>=6 else vols[-1]
    volratio = vols[-1]/vol5 if vol5 else 0
    cum5 = (closes[-1]/closes[-6]-1)*100 if len(closes)>=6 else 0
    dist_hi20 = (closes[-1]/hi20-1)*100
    dist_hi_all = (closes[-1]/hi_all-1)*100
    gaps = []
    for i in range(1, len(s)):
        g_up = s[i][2] > s[i-1][4]*1.005   # open > prev low*1.005 且跳空高于前收
        if s[i][2] > s[i-1][5]*1.01: gaps.append((s[i][1], 'gapup', round((s[i][2]/s[i-1][5]-1)*100,1)))
        if s[i][2] < s[i-1][5]*0.99: gaps.append((s[i][1], 'gapdn', round((s[i][2]/s[i-1][5]-1)*100,1)))
    bigvol = [(s[i][1], round(vols[i]/(sum(vols[max(0,i-5):i])/min(5,max(1,i)) if i>0 else vols[i]),1)) for i in range(max(1,len(s)-10), len(s)) if vols[i] > 2*(sum(vols[max(0,i-5):i])/min(5,max(1,i)))]
    out.write(f"### {code} {names.get(code,'?')} | last {last[1]} close={closes[-1]:.2f} pct={pcts[-1]:+.2f}% "
              f"| 5d={cum5:+.1f}% streak={streak} | vs MA5 {(closes[-1]/ma5-1)*100:+.1f}% MA10 {(closes[-1]/ma10-1)*100:+.1f}% MA20 {(closes[-1]/ma20-1)*100:+.1f}%"
              f" | dist20hi={dist_hi20:+.1f}% dist30hi={dist_hi_all:+.1f}% 20lo={lo20:.2f}"
              f" | volratio={volratio:.2f} | volspikes={bigvol} | gaps={gaps[-4:]}\n")
    out.write("    closes: " + " ".join(f"{c:.2f}({p:+.1f})" for c,p in zip(closes[-12:],pcts[-12:])) + "\n")
out.close()
print("done")
