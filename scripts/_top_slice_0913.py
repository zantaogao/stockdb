#!/usr/bin/env python3
"""样本外39天：fusion D1内部头部细分的20d超额（09-13）
回答：全截面单调的 fusion，头部前50名内部是否也有反转（对齐回放里 rk1-5 跑输的发现）。
ts_code 解析：6位码→在当日 daily 里能找到的唯一 ts_code（防 000001 沪/深/港混淆）。
"""
import duckdb, os, math, statistics
HOME=os.path.expanduser('~')
t=duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db',read_only=True)
t.execute("SET memory_limit='8GB'")
t.execute(f"ATTACH '{HOME}/.hermes/stockdb/signals.db' AS sig (READ_ONLY)")

rows=t.execute("""
  WITH cal AS (SELECT DISTINCT trade_date FROM daily),
  s AS (
    SELECT REPLACE(date,'-','') d, stock_code code6, fusion_score sc,
           ROW_NUMBER() OVER (PARTITION BY date ORDER BY fusion_score DESC) rk
    FROM sig.signal_history WHERE fusion_score IS NOT NULL),
  idm AS (  -- 6位码→ts_code 唯一映射（用最后一天快照即可，退市票自然被 join 不上）
    SELECT substr(ts_code,1,6) c6, ANY_VALUE(ts_code) ts_code
    FROM daily WHERE trade_date>='20260801' GROUP BY 1 HAVING COUNT(DISTINCT ts_code)=1),
  px AS (
    SELECT ts_code, trade_date, aopen, aclose,
           LEAD(aclose,20) OVER (PARTITION BY ts_code ORDER BY trade_date) exit_c,
           LEAD(trade_date,21) OVER (PARTITION BY ts_code ORDER BY trade_date) mat
    FROM (SELECT d.ts_code, d.trade_date,
                 d.open *COALESCE(a.adj_factor,1) aopen,
                 d.close*COALESCE(a.adj_factor,1) aclose
          FROM daily d LEFT JOIN adj_factor a USING(ts_code,trade_date)
          WHERE d.trade_date>='20260601')),
  entry AS (  -- 入场=信号日次一交易日开盘；先按(票,日)去重再算收益
    SELECT s.d, s.rk, p.aopen,
           LEAST(p.trade_date, '20260814') IS NOT NULL ok,
           p.exit_c, p.mat,
           ROW_NUMBER() OVER (PARTITION BY s.d, s.code6 ORDER BY p.trade_date) rn
    FROM s JOIN idm ON idm.c6=s.code6
    JOIN px p ON p.ts_code=idm.ts_code AND p.trade_date > s.d
    WHERE s.rk<=500 AND p.exit_c IS NOT NULL AND p.mat IS NOT NULL),
  e1 AS (SELECT d, rk, exit_c/aopen-1 ret FROM entry WHERE rn=1),
  mkt AS (SELECT d, AVG(ret) m FROM e1 GROUP BY 1)
SELECT e.d, e.rk, e.ret-m.m ex FROM e1 e JOIN mkt m USING(d)
""").fetchall()

buckets=[(1,20,'top1-20'),(21,50,'21-50'),(51,100,'51-100'),(101,200,'101-200'),(201,500,'201-500')]
print(f"D1头部细分 20d等权超额（样本外，{len(set(r[0] for r in rows))} 个成熟信号日）")
for lo,hi,name in buckets:
    perday={}
    for d,rk,v in rows:
        if lo<=rk<=hi: perday.setdefault(d,[]).append(v)
    vals=[statistics.mean(v) for v in perday.values()]
    n=len(vals); m=statistics.mean(vals)*100; sd=statistics.stdev(vals)
    print(f"  {name:10s} n={n:3d} 日均ex20={m:+.3f}%  t={m/(sd/math.sqrt(n)):+.2f}")
