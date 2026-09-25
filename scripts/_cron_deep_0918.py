import duckdb, os
H = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{H}/tushare.db', read_only=True)

hold = {'603202':'天有为','002454':'松芝股份','605598':'上海港湾','688093':'世华科技','300658':'延江股份','688186':'广大特材','301110':'青木科技','301093':'华兰股份','001332':'锡装股份','603966':'法兰泰克','301237':'和顺科技','601615':'明阳智能','688191':'智洋创新','301283':'聚胶股份','600076':'康欣新材','301590':'优优绿能'}
lists = {
 '三模型融合': ['301575','301590','301233','688081','300970','603811','688377','688399','301042','603966'],
 'CMMR独立': ['000430','000567','000702','000796','000890','000937','001258','001299','001366','002094'],
 'CMMR+': ['300970','688217','301181','301106','300621','301198','301167','301519','300935','600638'],
 '10d独立': ['688356','600103','600076','002470','000565','603958','002349','688300','603999','002161'],
 '中枢版': ['000923','002405','300442','000155','601106','301111','300007','688119','000534','301110'],
 '中枢+三模型': ['300651','301110','688335','301503','600791','301042','688021','002969','003038','601778'],
}
codes = sorted(set(list(hold) + [c for v in lists.values() for c in v]))
def ts_of(c): return c + ('.SH' if c[0] in '569' else '.SZ')
tsmap = {ts_of(c): c for c in codes}
ph = ','.join(f"'{k}'" for k in tsmap)
q = f"""
SELECT ts_code, trade_date, close, pct_chg, vol, high, low, open FROM daily
WHERE ts_code IN ({ph}) AND trade_date >= '20260801'
ORDER BY ts_code, trade_date
"""
rows = t.execute(q).fetchall()
data = {}
for r in rows:
    data.setdefault(r[0][:6], []).append(r[1:])

def analyze(code, name):
    d = data.get(code)
    if not d or len(d) < 25: return f'{name} {code}: 数据不足({len(d) if d else 0})'
    closes = [x[1] for x in d]; vols = [x[3] for x in d]; chg = [x[2] for x in d]
    highs = [x[4] for x in d]; lows = [x[5] for x in d]; opens = [x[6] for x in d]
    c = closes[-1]
    ma20 = sum(closes[-20:])/20
    import statistics
    sd = statistics.pstdev(closes[-20:])
    up_band, lo_band = ma20+2*sd, ma20-2*sd
    bollpos = (c-lo_band)/(up_band-lo_band)*100 if up_band>lo_band else 50
    dev = (c/ma20-1)*100
    r5 = (closes[-1]/closes[-6]-1)*100
    hi20 = max(highs[-20:]); dist_hi = (c/hi20-1)*100
    # 连续涨跌天数
    streak = 0
    for x in reversed(chg):
        if streak == 0: streak = 1 if x>0 else (-1 if x<0 else 0)
        elif streak>0 and x>0: streak+=1
        elif streak<0 and x<0: streak-=1
        else: break
    # 近10日放量日（vol>2x前5日均量）
    spikes = []
    for i in range(len(d)-10, len(d)):
        if i>=5 and vols[i] > 2*sum(vols[i-5:i])/5:
            spikes.append((d[i][0][4:], round(vols[i]/(sum(vols[i-5:i])/5),1)))
    # 近10日跳空缺口（open > 昨high 或 < 昨low）
    gaps = []
    for i in range(len(d)-8, len(d)):
        if opens[i] > highs[i-1]: gaps.append((d[i][0][4:],'向上'))
        elif opens[i] < lows[i-1]: gaps.append((d[i][0][4:],'向下'))
    return (f'{name} {code}: 收{c} 今{chg[-1]:+.1f}% 5日{r5:+.1f}% 偏离MA20 {dev:+.1f}% 布林{bollpos:.0f}% '
            f'距20日高{dist_hi:+.1f}% 连续{streak:+d}日 放量{spikes} 缺口{gaps} '
            f'近5日涨跌{[round(x,1) for x in chg[-5:]]}')

print('##### 主账户持仓 #####')
for c_, n_ in hold.items(): print(analyze(c_, n_))
for ln, lst in lists.items():
    print(f'##### {ln} #####')
    for c_ in lst:
        nm = t.execute(f"SELECT name FROM stock_basic WHERE ts_code='{ts_of(c_)}'").fetchone()
        print(analyze(c_, nm[0] if nm else '?'))

print('##### 主线板块龙头交叉验证: 今日半导体/机械基件涨幅前3 #####')
for ind in ['半导体','机械基件']:
    top = t.execute(f"""SELECT d.ts_code, b.name, d.pct_chg FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
      WHERE d.trade_date='20260918' AND b.industry='{ind}' ORDER BY d.pct_chg DESC LIMIT 3""").fetchall()
    print(ind, [(r[1], round(r[2],1)) for r in top])
    for r in top[:3]:
        print('  ', analyze(r[0][0:6], r[1]))
