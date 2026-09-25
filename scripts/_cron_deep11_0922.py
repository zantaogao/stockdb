#!/usr/bin/env python3
# 逐票形态指标：六榜top10 + 主账户持仓（信号日0922）
import duckdb, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
t = duckdb.connect('tushare.db', read_only=True)

boards = {
 '三模型': ['603585.SH','300854.SZ','300651.SZ','300492.SZ','688171.SH','300982.SZ','301219.SZ','301590.SZ','301259.SZ','688335.SH'],
 'CMMR独立': ['000017.SZ','000426.SZ','000505.SZ','000523.SZ','000679.SZ','000683.SZ','000798.SZ','000890.SZ','000892.SZ','002041.SZ'],
 'CMMR融合': ['603585.SH','300614.SZ','301156.SZ','002760.SZ','002858.SZ','300500.SZ','300621.SZ','003003.SZ','002809.SZ','605001.SH'],
 '10d独立': ['001216.SZ','600743.SH','000668.SZ','601811.SH','600825.SH','301237.SZ','603958.SH','300413.SZ','300120.SZ','600551.SH'],
 '中枢版': ['001318.SZ','300384.SZ','300854.SZ','603927.SH','001269.SZ','301370.SZ','000514.SZ','300405.SZ','688737.SH','002921.SZ'],
 '中枢三模型': ['300854.SZ','300651.SZ','300520.SZ','688737.SH','002868.SZ','002861.SZ','300228.SZ','300887.SZ','000633.SZ','300982.SZ'],
 '主账户': ['301093.SZ','688191.SH','301237.SZ','300658.SZ','688093.SH','301283.SZ','001332.SZ','002454.SZ','600076.SH','603966.SH','301575.SZ','603202.SH','301590.SZ','688186.SH','601615.SH','603811.SH','301110.SZ','605598.SH'],
}

cache = {}
def series(code):
    if code in cache: return cache[code]
    rows = t.execute("SELECT trade_date,open,high,low,close,pct_chg,vol FROM daily WHERE ts_code=? AND trade_date>='20260701' ORDER BY trade_date", [code]).fetchall()
    cache[code] = rows
    return rows

for b, codes in boards.items():
    print(f'===== {b} =====')
    seen = set()
    for c in codes:
        if c in seen and b != '主账户': continue
        seen.add(c)
        rows = series(c)
        if not rows or rows[-1][0] != '20260922':
            print(f'{c} 无0922数据 len={len(rows)}'); continue
        closes = [r[4] for r in rows]
        vols = [r[6] for r in rows]
        n = len(closes)
        ma20 = sum(closes[-20:])/20
        var = sum((x-ma20)**2 for x in closes[-20:])/20
        sd = var**0.5
        hi20 = max(r[2] for r in rows[-20:]); lo20 = min(r[3] for r in rows[-20:])
        cl = closes[-1]
        bpos = (cl-(ma20-2*sd))/((ma20+2*sd)-(ma20-2*sd))*100 if sd>0 else -1
        chg5 = (cl/closes[-6]-1)*100 if n>=6 else None
        dist_hi = (cl/hi20-1)*100
        # streak
        streak = 0
        for r in reversed(rows):
            if r[5] > 0: streak += 1
            else: break
        if streak == 0:
            for r in reversed(rows):
                if r[5] < 0: streak -= 1
                else: break
        volr = vols[-1]/(sum(vols[-6:-1])/5) if n>=6 and sum(vols[-6:-1])>0 else None
        gap = '跳空高开' if rows[-1][1] > rows[-2][2] else ('跳空低开' if rows[-1][1] < rows[-2][3] else '')
        ma10 = sum(closes[-10:])/10
        d = {r[0]: r for r in rows}
        hist = ' '.join(f"{r[0][4:]}:{r[5]:+.1f}" for r in rows[-10:])
        print(f'{c} 收{cl:.2f} 今日{rows[-1][5]:+.2f}% 5日{chg5:+.1f}% 连{streak:+d} 量比{volr:.1f} 布林{bpos:.0f}% MA20={ma20:.2f} MA10={ma10:.2f} 距20日高{dist_hi:+.1f}% 20日低{lo20:.2f} {gap}')
        print(f'    近10日: {hist}')
print('DONE')
