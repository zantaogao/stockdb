#!/usr/bin/env python3
"""满仓运作环境分层分析（09-13，回放跑完后的第二段）
输入：replay/regime_replay.duckdb replay_top50（1138天×top50，final_score 降序）
     tushare.db daily + adj_factor（复权）、index_daily 000852（环境标签+基准）
口径：信号日 D 收盘出分 → T+1 开盘（复权开盘价）买入；
     ret1 = c(D+1)/o(D+1)-1，ret5 = c(D+5)/o(D+1)-1，ret10 = c(D+10)/o(D+1)-1
     基准同窗口：b5 = ci(D+5)/ci(D+1)-1（基准也从 D+1 收盘近似入场，与个股可比）
环境（D 日中证1000收盘涨跌幅）：crash≤-3 / mild(-3,-1] / flat(-1,1) / up≥1
     注：生产规则大跌市停买——crash 行是"如果买了会怎样"的反事实。
     注意 in-sample：模型训练含回放期样本，只做分环境相对比较，不当无偏IC。
输出：replay/regime_returns.duckdb replay_returns 表（幂等重建）+ stdout 汇总
"""
import os
import duckdb
import pandas as pd

HOME = os.path.expanduser('~')
REPLAY = f'{HOME}/.hermes/stockdb/replay/regime_replay.duckdb'
TUSHARE = f'{HOME}/.hermes/stockdb/tushare.db'
OUT = f'{HOME}/.hermes/stockdb/replay/regime_returns.duckdb'

def main():
    t = duckdb.connect(TUSHARE, read_only=True)
    t.execute("SET memory_limit='8GB'")
    t.execute(f"ATTACH '{REPLAY}' AS rep (READ_ONLY)")

    # 信号票复权价 + 前推窗口（LEAD 需要连续序列，从 20210601 起保证头部窗口）
    t.execute("""
      CREATE OR REPLACE TEMP TABLE px AS
      WITH base AS (
        SELECT d.ts_code, d.trade_date,
               d.open * a.adj_factor  AS aopen,
               d.close * a.adj_factor AS aclose
        FROM daily d
        JOIN adj_factor a USING (ts_code, trade_date)
        WHERE d.trade_date >= '20210601'
          AND d.ts_code IN (SELECT ts_code FROM rep.replay_top50 GROUP BY ts_code)
      )
      SELECT *,
             LEAD(aclose, 4) OVER w AS c4,   -- 入场日=D+1行：+4行=close(D+5)
             LEAD(aclose, 9) OVER w AS c9    -- +9行=close(D+10)
      FROM base
      WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date)
    """)

    # 指数环境标签 + 基准各窗口收益
    t.execute("""
      CREATE OR REPLACE TEMP TABLE idx AS
      WITH b AS (
        SELECT strftime(date,'%Y%m%d') AS d, close, change_pct
        FROM index_daily WHERE index_code='000852'
      )
      SELECT *,
             LEAD(close,1)  OVER ob AS ci1,
             LEAD(close,5)  OVER ob AS ci5,
             LEAD(close,10) OVER ob AS ci10,
             LAG(close,1)   OVER ob AS cprev
      FROM b
      WINDOW ob AS (ORDER BY d)
    """)

    # 个股入场日 = 信号日之后的第一个交易日（停牌顺延），在该行上取 LEAD 列
    res = t.execute("""
      WITH entry AS (
        SELECT s.date, s.ts_code, s.final_score, s.fusion,
                   p.aopen AS o1, p.aclose AS c1, p.c4, p.c9,
                   ROW_NUMBER() OVER (PARTITION BY s.date, s.ts_code ORDER BY p.trade_date) AS rn
        FROM rep.replay_top50 s
        JOIN px p ON p.ts_code = s.ts_code AND p.trade_date > s.date
      ),
      e1 AS (  -- 09-13 fix：先只留入场行，再排 rk（此前 rk 在 join 全窗口上算，被停牌股污染）
        SELECT *, ROW_NUMBER() OVER (PARTITION BY date
                                     ORDER BY final_score DESC, fusion DESC) AS rk
        FROM entry WHERE rn = 1
      )
      SELECT e.date, e.ts_code, e.rk,
             CASE WHEN i.change_pct <= -3 THEN 'crash'
                  WHEN i.change_pct <= -1 THEN 'mild'
                  WHEN i.change_pct <   1 THEN 'flat'
                  ELSE 'up' END AS regime,
             substr(e.date,1,4) AS yr,
             e.c1/e.o1-1  AS ret1,
             e.c4/e.o1-1  AS ret5,
             e.c9/e.o1-1  AS ret10,
             i.ci1/i.close-1     AS b1,
             i.ci5/i.ci1-1     AS b5,
             i.ci10/i.ci1-1    AS b10
      FROM e1 e
      LEFT JOIN idx i ON i.d = e.date
    """).fetchall()
    cols = ['date','ts_code','rk','regime','yr','ret1','ret5','ret10','b1','b5','b10']
    df = pd.DataFrame(res, columns=cols)
    n_dropped = df.ret1.isna().sum()
    df = df.dropna(subset=['ret1','b5','b10'])
    for k in (1,5,10):
        df[f'ex{k}'] = df[f'ret{k}'] - df[f'b{k}']

    o = duckdb.connect(OUT)
    o.register('tmp_res', df)
    o.execute("CREATE OR REPLACE TABLE replay_returns AS SELECT * FROM tmp_res")
    o.close()
    print(f"落盘 {OUT}: {len(df)} 行（丢 {n_dropped} 行无T+1收盘的尾部）", flush=True)

    o = duckdb.connect(OUT, read_only=True)
    order = "ARRAY['crash','mild','flat','up']"
    print("\n== 全期 2022-2026 top10 分环境: regime 天数 ret1% ret5% ret10% | ex5% ex10% | 胜率%(5d) 超额胜率%(5d)")
    for r in o.execute(f"""
      SELECT regime, COUNT(DISTINCT date),
             ROUND(AVG(ret1)*100,2), ROUND(AVG(ret5)*100,2), ROUND(AVG(ret10)*100,2),
             ROUND(AVG(ex5)*100,2), ROUND(AVG(ex10)*100,2),
             ROUND(100.0*SUM(CASE WHEN ret5>0 THEN 1 ELSE 0 END)/COUNT(*),1),
             ROUND(100.0*SUM(CASE WHEN ex5>0 THEN 1 ELSE 0 END)/COUNT(*),1)
      FROM replay_returns WHERE rk<=10
      GROUP BY 1 ORDER BY list_position({order}, regime)
    """).fetchall(): print(r)

    print("\n== 逐年×环境 top10: 年 环境 n ret5% ex5% 超额胜率% ret10% ex10%")
    for r in o.execute(f"""
      SELECT yr, regime, COUNT(*),
             ROUND(AVG(ret5)*100,2), ROUND(AVG(ex5)*100,2),
             ROUND(100.0*SUM(CASE WHEN ex5>0 THEN 1 ELSE 0 END)/COUNT(*),1),
             ROUND(AVG(ret10)*100,2), ROUND(AVG(ex10)*100,2)
      FROM replay_returns WHERE rk<=10
      GROUP BY 1,2 ORDER BY 1, list_position({order}, regime)
    """).fetchall(): print(r)

    print("\n== top10 vs 11-50 对照: 环境 档位 ex5% ex10%")
    for r in o.execute(f"""
      SELECT regime, CASE WHEN rk<=10 THEN 'top10' ELSE 'tail40' END,
             ROUND(AVG(ex5)*100,2), ROUND(AVG(ex10)*100,2)
      FROM replay_returns GROUP BY 1,2 ORDER BY 1,2
    """).fetchall(): print(r)

    print("\n== 大跌市(crash)单独看 top10 明细按年: 年 n ret1% ret5%")
    for r in o.execute("""
      SELECT yr, COUNT(*), ROUND(AVG(ret1)*100,2), ROUND(AVG(ret5)*100,2)
      FROM replay_returns WHERE rk<=10 AND regime='crash' GROUP BY 1 ORDER BY 1
    """).fetchall(): print(r)
    o.close()

if __name__ == '__main__':
    main()
