import duckdb, sqlite3, os, json
os.chdir('/Users/zantao/.hermes/stockdb')
con = duckdb.connect('tushare.db', read_only=True)

# 1) 近10交易日行业等权涨幅
tds = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date<='20260930' ORDER BY trade_date DESC LIMIT 10").fetchall()]
tds = sorted(tds)
print("TRADE_DATES:", tds)
ind_daily = {}
for td in tds:
    rows = con.execute("""
      SELECT b.industry, AVG(d.pct_chg), COUNT(*) FROM daily d
      JOIN stock_basic b ON d.ts_code=b.ts_code
      WHERE d.trade_date=? AND b.industry IS NOT NULL AND b.industry!=''
      GROUP BY b.industry HAVING COUNT(*)>=8
    """, [td]).fetchall()
    ind_daily[td] = {n: v for n, v, c in rows}
# 按今日排名输出近10日矩阵 top20(今日) + 5日累计
today = tds[-1]
rank = sorted(ind_daily[today].items(), key=lambda x: -x[1])
print("\n=== 今日行业涨幅 TOP15 (近10日该行业每日涨幅) ===")
for n, v in rank[:15]:
    series = [round(ind_daily[t].get(n, float('nan')),2) for t in tds]
    cum5 = sum(ind_daily[t].get(n,0) for t in tds[-5:])
    # 连续强势天数(今日往前 pct_chg>0)
    streak=0
    for t in reversed(tds):
        if ind_daily[t].get(n, -99) > 0: streak+=1
        else: break
    print(f"{n}: today {v:+.2f}% cum5 {cum5:+.2f}% streak {streak} series {series}")
print("\n=== 今日行业跌幅 BOT8 ===")
for n, v in rank[-8:]:
    cum5 = sum(ind_daily[t].get(n,0) for t in tds[-5:])
    print(f"{n}: today {v:+.2f}% cum5 {cum5:+.2f}%")
print("\n=== 近5日累计涨幅 TOP10 (持续主线候选) ===")
cum = {n: sum(ind_daily[t].get(n,0) for t in tds[-5:]) for n in ind_daily[today]}
for n,c in sorted(cum.items(), key=lambda x:-x[1])[:10]:
    series=[round(ind_daily[t].get(n,float('nan')),2) for t in tds[-5:]]
    print(f"{n}: cum5 {c:+.2f}% series {series}")

# 2) 涨跌家数近8日
print("\n=== 宽度近8日 ===")
for r in con.execute("""
SELECT trade_date, SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END), SUM(CASE WHEN pct_chg<0 THEN 1 ELSE 0 END), COUNT(*)
FROM daily WHERE trade_date>='20260918' GROUP BY trade_date ORDER BY trade_date""").fetchall():
    print("  ", r[0], "up", r[1], "dn", r[2], "tot", r[3], f"up% {r[1]/r[3]*100:.0f}")

# 3) 上证50 vs 中证1000 风格近8日
print("\n=== 风格 000016/000852 近8日 pct_chg ===")
for ts in ('000016.SH','000852.SH'):
    rows = con.execute(f"SELECT trade_date,pct_chg FROM index_daily_raw WHERE ts_code='{ts}' ORDER BY trade_date DESC LIMIT 8").fetchall()
    print(ts, [(r[0], round(r[1],2)) for r in reversed(rows)])
con.close()
