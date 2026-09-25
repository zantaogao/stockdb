#!/usr/bin/env python3
# 资金流观察哨 v1（2026-09-04 立项："新维度观察点"，只记录不进模型）
# 数据源: tushare.db moneyflow_raw（16:00 增量cron已维护）+ daily/adj_factor 算前向收益
# 观察因子（单位:万元口径的比值；main=大单+特大单净额）:
#   main_net_1d_pct  = 当日main净额/流通市值
#   main_net_5d_pct  = 5日滚动累计main净额/流通市值
#   pos_days_11d     = 最近11个交易日中main净额为正的天数(0-11，净买入持续性)
#   elg_net_liq_pct  = 特大单净额/(四类买卖总额) 特大单结构异动
# 前向收益: LEAD 5个交易日的复权close收益（T+5未出则为NULL自动剔除，无未来函数）
# 输出: signals.db mf_observer_daily（逐票日值，仅最近30个交易日滚动；全量可由本脚本重算）
#       signals.db mf_observer_ic_daily（逐日全市场 Rank IC，INSERT OR IGNORE 幂等）
# 不进任何评分/模型/交易链路。
import os, sys, sqlite3, math, statistics, duckdb, datetime as dt
BASE = os.path.expanduser('~/.hermes/stockdb')
SIN = os.path.join(BASE, 'signals.db')
START = os.environ.get('MF_OBS_START', '20250101')
# CTE 加载缓冲：main_net5/pos_days 窗口需要 START 前≥11个交易日垫底，取60自然日
LOAD = (dt.datetime.strptime(START, '%Y%m%d') - dt.timedelta(days=60)).strftime('%Y%m%d')

d = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
sql = f"""
WITH mf AS (
  SELECT ts_code, trade_date,
         (buy_lg_amount - sell_lg_amount + buy_elg_amount - sell_elg_amount) AS main_net,
         (buy_elg_amount - sell_elg_amount) AS elg_net,
         (buy_sm_amount+sell_sm_amount+buy_md_amount+sell_md_amount
           +buy_lg_amount+sell_lg_amount+buy_elg_amount+sell_elg_amount) AS liq
  FROM moneyflow_raw WHERE trade_date >= '{LOAD}'
), db AS (
  SELECT ts_code, trade_date, circ_mv FROM daily_basic WHERE trade_date >= '{LOAD}'
), adj AS (
  SELECT dd.ts_code, dd.trade_date, dd.close * coalesce(a.adj_factor,1) AS ac
  FROM daily dd LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE dd.trade_date >= '{LOAD}'
), j AS (
  SELECT mf.ts_code, mf.trade_date, main_net, elg_net, liq, db.circ_mv, adj.ac,
    SUM(main_net) OVER w   AS main_net5,
    count_if(main_net > 0) OVER (PARTITION BY mf.ts_code ORDER BY mf.trade_date
        ROWS BETWEEN 10 PRECEDING AND CURRENT ROW) AS pos_days,
    LEAD(adj.ac, 5) OVER w AS ac_fwd5
  FROM mf
  JOIN db USING (ts_code, trade_date)
  JOIN adj USING (ts_code, trade_date)
  WINDOW w AS (PARTITION BY mf.ts_code ORDER BY mf.trade_date
              ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
)
SELECT trade_date, ts_code,
  main_net  / nullif(circ_mv,0) AS main_net_1d_pct,
  main_net5 / nullif(circ_mv,0) AS main_net_5d_pct,
  pos_days                      AS pos_days_11d,
  elg_net   / nullif(liq,0)     AS elg_net_liq_pct,
  ac_fwd5 / nullif(ac,0) - 1    AS fwd_ret_5d
FROM j
"""
df = d.execute(sql).df()
d.close()
if df.empty:
    print('MF_OBS: 无数据'); sys.exit(0)
df = df.dropna(subset=['main_net_1d_pct'])

c = sqlite3.connect(SIN)
c.executescript("""
CREATE TABLE IF NOT EXISTS mf_observer_daily(
  date TEXT, code TEXT, main_net_1d_pct REAL, main_net_5d_pct REAL,
  pos_days_11d INT, elg_net_liq_pct REAL,
  PRIMARY KEY(date, code));
CREATE TABLE IF NOT EXISTS mf_observer_ic_daily(
  date TEXT, factor_name TEXT, rank_ic REAL, p_value REAL, n_stocks INT,
  ret_horizon TEXT DEFAULT '5d',
  PRIMARY KEY(date, factor_name));
""")
cut = sorted(df.trade_date.unique())[-30]
rows = [(r.trade_date[:4]+'-'+r.trade_date[4:6]+'-'+r.trade_date[6:], r.ts_code,
         r.main_net_1d_pct, r.main_net_5d_pct, int(r.pos_days_11d), r.elg_net_liq_pct)
        for r in df[df.trade_date >= cut].itertuples()]
c.executemany("INSERT OR REPLACE INTO mf_observer_daily VALUES (?,?,?,?,?,?)", rows)

def rank_ic(pairs):
    v = [(a, b) for a, b in pairs if a is not None and b is not None and b == b]
    n = len(v)
    if n < 100: return None
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        rk = [0.0]*len(xs); i = 0
        while i < len(order):
            j = i
            while j+1 < len(order) and xs[order[j+1]] == xs[order[i]]: j += 1
            avg = (i+j)/2 + 1
            for k in range(i, j+1): rk[order[k]] = avg
            i = j+1
        return rk
    xa, xb = ranks([x[0] for x in v]), ranks([x[1] for x in v])
    ma, mb = statistics.mean(xa), statistics.mean(xb)
    cov = sum((a-ma)*(b-mb) for a, b in zip(xa, xb))
    va = math.sqrt(sum((a-ma)**2 for a in xa)); vb = math.sqrt(sum((b-mb)**2 for b in xb))
    if va == 0 or vb == 0: return None
    ic = cov/(va*vb)
    t = ic*math.sqrt((n-2)/max(1e-12, 1-ic*ic))
    p = math.erfc(abs(t)/math.sqrt(2))
    return ic, p, n

ic_rows = []
FACTORS = ['main_net_1d_pct', 'main_net_5d_pct', 'pos_days_11d', 'elg_net_liq_pct']
for date, g in df.groupby('trade_date'):
    d_iso = date[:4]+'-'+date[4:6]+'-'+date[6:]
    for f in FACTORS:
        r = rank_ic(list(zip(g[f], g.fwd_ret_5d)))
        if r: ic_rows.append((d_iso, f, r[0], r[1], r[2], '5d'))
c.executemany("INSERT OR IGNORE INTO mf_observer_ic_daily VALUES (?,?,?,?,?,?)", ic_rows)
c.commit()
n_obs = c.execute("SELECT COUNT(*), MAX(date) FROM mf_observer_daily").fetchone()
n_ic = c.execute("SELECT COUNT(DISTINCT date) FROM mf_observer_ic_daily").fetchone()[0]
print(f"MF_OBS ✅ 逐票值 {n_obs[0]} 行(截至{n_obs[1]}); IC 已计 {n_ic} 个交易日")
for f in FACTORS:
    r = c.execute("SELECT AVG(rank_ic), AVG(CASE WHEN p_value<0.05 THEN 1.0 ELSE 0 END), COUNT(*) FROM mf_observer_ic_daily WHERE factor_name=?", (f,)).fetchone()
    print(f"  {f:18s} 日均IC={r[0]:+.4f} 显著天={r[1]:.0%} n={r[2]}")
c.close()