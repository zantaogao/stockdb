# -*- coding: utf-8 -*-
"""指数均线/支撑阻力 + 宽度统计（2026-09-15）"""
import duckdb, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
for code, nm in [('000001.SH', '上证'), ('000852.SH', '中证1000'), ('399006.SZ', '创业板')]:
    rows = con.execute("SELECT trade_date, close, high, low, amount FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60", (code,)).fetchall()
    rows = list(reversed(rows))
    cl = [float(r[1]) for r in rows]
    last = cl[-1]
    ma5, ma10, ma20, ma60 = sum(cl[-5:]) / 5, sum(cl[-10:]) / 10, sum(cl[-20:]) / 20, sum(cl[-60:]) / 60
    hi20, lo20 = max(float(r[2]) for r in rows[-20:]), min(float(r[3]) for r in rows[-20:])
    hi60, lo60 = max(float(r[2]) for r in rows), min(float(r[3]) for r in rows)
    print(f"{nm}({code}) 收 {last:.2f}")
    print(f"  MA5 {ma5:.2f}({(last/ma5-1)*100:+.2f}%) MA10 {ma10:.2f}({(last/ma10-1)*100:+.2f}%) MA20 {ma20:.2f}({(last/ma20-1)*100:+.2f}%) MA60 {ma60:.2f}({(last/ma60-1)*100:+.2f}%)")
    print(f"  20日高 {hi20:.2f}(距{(last/hi20-1)*100:+.2f}%) 20日低 {lo20:.2f}(距{(last/lo20-1)*100:+.2f}%) | 60日高 {hi60:.2f}(距{(last/hi60-1)*100:+.2f}%) 60日低 {lo60:.2f}(距{(last/lo60-1)*100:+.2f}%)")
    print(f"  近5日成交额(亿): " + " ".join(f"{r[0][4:]}:{float(r[4])/1e5:.0f}" for r in rows[-5:]))

print("\n== 宽度（tushare.daily 全市场）近6日 ==")
days = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 8").fetchall()]
for d in days:
    r = con.execute("""SELECT COUNT(*), SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END),
                              SUM(CASE WHEN pct_chg>5 THEN 1 ELSE 0 END), SUM(CASE WHEN pct_chg<-5 THEN 1 ELSE 0 END),
                              SUM(CASE WHEN pct_chg>=9.8 THEN 1 ELSE 0 END), SUM(CASE WHEN pct_chg<=-9.8 THEN 1 ELSE 0 END),
                              AVG(pct_chg), SUM(amount)/1e5
                       FROM daily WHERE trade_date=?""", (d,)).fetchone()
    print(f"  {d}: n={r[0]} 涨占比={r[1]/r[0]*100:.0f}% 强>5%={r[2]} 弱<-5%={r[3]} 涨停={r[4]} 跌停={r[5]} 均涨={r[6]:+.2f}% 额={r[7]:.0f}亿")
con.close()
