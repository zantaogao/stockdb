#!/usr/bin/env python3
"""fusion/reg10 全截面十分位排序形态检验（09-13）
复刻 09-06 _cmmr_rank_shape_0906.py 判定口径：
每信号日全市场按分数降序分10组（D1=最高分组），各组等权持有收益减当日市场等权，
跨日平均。指标：D1..D10 曲线、首尾差 D1-D10、组序Spearman ρ、U型度=min(D1,D10)-min(D2..D9)。
收益口径：信号日 D → T+1开盘(复权)入场 → 持有20交易日出场（与09-06 20d窗对齐）。
只取成熟日（D+21 有数据）。分数列分别测 fusion_score 与 reg10。
"""
import duckdb, os, math, sqlite3
HOME = os.path.expanduser('~')
t = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
t.execute("SET memory_limit='8GB'")
t.execute(f"ATTACH '{HOME}/.hermes/stockdb/signals.db' AS sig (READ_ONLY)")

# 信号（去掉分数空/占位：当日去重分数<5个=占位期跳过）
SIG_COLS = ['fusion_score', 'reg10', 'reg20', 'reg40']
for col in SIG_COLS:
    res = t.execute(f"""
      WITH s AS (
        SELECT REPLACE(date,'-','') AS d,
               CASE WHEN LENGTH(stock_code)=6 THEN stock_code
                    ELSE stock_code END AS code6,
               {col} AS sc
        FROM sig.signal_history
        WHERE {col} IS NOT NULL
      ),
      s2 AS (
        SELECT d FROM s GROUP BY d HAVING COUNT(DISTINCT sc) >= 5
      ),
      px AS (
        SELECT ts_code, trade_date, aopen, aclose,
               LEAD(aclose,20) OVER (PARTITION BY ts_code ORDER BY trade_date) AS exit_c,
               LEAD(trade_date,21) OVER (PARTITION BY ts_code ORDER BY trade_date) AS mat_chk
        FROM (SELECT d.ts_code, d.trade_date,
                     d.open *COALESCE(a.adj_factor,1) AS aopen,
                     d.close*COALESCE(a.adj_factor,1) AS aclose
              FROM daily d LEFT JOIN adj_factor a USING(ts_code,trade_date)
              WHERE d.trade_date >= '20260601')
      ),
      entry AS (
        SELECT s.d, s.code6, s.sc,
               p.exit_c / p.aopen - 1 AS ret
        FROM s JOIN s2 ON s2.d = s.d
        JOIN (SELECT *, substr(ts_code,1,6) AS code6 FROM px WHERE trade_date >= '20260701') p
          ON p.code6 = s.code6
         AND p.trade_date = (SELECT MIN(trade_date) FROM px q
                             WHERE q.ts_code = p.ts_code AND q.trade_date > s.d)
        WHERE p.exit_c IS NOT NULL AND p.mat_chk IS NOT NULL
      ),
      mkt AS (SELECT d, AVG(ret) mret FROM entry GROUP BY 1),
      grp AS (
        SELECT e.d, NTILE(10) OVER (PARTITION BY e.d ORDER BY e.sc ASC) AS g,  -- g10=最高分
               e.ret - m.mret AS ex
        FROM entry e JOIN mkt m USING (d)
      )
      SELECT g, AVG(ex)*100, COUNT(*) FROM grp GROUP BY 1 ORDER BY 1
    """).fetchall()
    if not res:
        print(f'{col}: 无成熟样本'); continue
    curve = {g: v for g, v, n in res}
    # D1=最高分 → 用 g10..g1
    d = [curve.get(11-i) for i in range(1, 11)]
    days = sum(n for _,_,n in res)//10
    d1_d10 = d[0]-d[9]
    # Spearman ρ(分数组序, 组超额)
    xs = list(range(1,11)); ys = sorted(d).index  # placeholder
    ys_ranked = {v: i for i, v in enumerate(sorted(d))}
    rho_num = sum((x - 5.5)*(ys_ranked[v]+1 - 5.5) for x, v in zip(xs, d))
    rho_den = math.sqrt(sum((x-5.5)**2 for x in xs) * sum((y+1-5.5)**2 for y in d))
    rho = rho_num/rho_den if rho_den else float('nan')
    u_shape = min(d[0], d[9]) - min(d[1:9])
    print(f"\n== {col}  (成熟日~{days},  D1=最高分 → D10=最低分)")
    print('  ' + '  '.join(f'D{i+1}:{v:+.2f}' for i, v in enumerate(d)))
    print(f'  首尾差D1-D10={d1_d10:+.2f}pp  Spearmanρ={rho:+.2f}  U型度={u_shape:+.2f}pp')
