#!/usr/bin/env python3
"""fusion_center_engine.py - 中枢版融合信号（2026-08-06 新增，独立于 fusion_3f_engine）
打分 = -(|ma_z| + |flow_z| + |vol_z|)：三因子离截面中枢越近越好
（17年回测发现三因子为倒U型信息，线性打分选极端=负超额；中枢化样本外 IC +0.060 t=+37，
牛/熊/震荡全环境显著正，详见 model-ic-evaluation）
信号分级：score 前 15% = 强买（对标 fusion_3f 强买口径）；reg10 不参与（模型预测无法历史化）
用法：python3 -B scripts/fusion_center_engine.py [YYYYMMDD]
"""
import duckdb, numpy as np, pandas as pd, sqlite3, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TUSHARE_DB = BASE / 'tushare.db'
STATE_DB = BASE / 'signals.db'  # v2温层

def main(target_date=None):
    t = duckdb.connect(str(TUSHARE_DB), read_only=True)
    last_td = str(t.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0])
    d = (target_date or last_td).replace('-', '')
    d_iso = f'{d[:4]}-{d[4:6]}-{d[6:]}'  # DuckDB DATE 运算需要 ISO 格式
    df = t.execute("""
    WITH base AS (
        SELECT d.ts_code, d.trade_date, d.close, d.vol,
            LAG(d.close, 4) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date) AS c4,
            LAG(d.close, 6) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date) AS c6,
            AVG(d.vol) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS vol5,
            AVG(d.close) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS pa,
            STDDEV(d.close) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ps,
            AVG(d.vol) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS va,
            STDDEV(d.vol) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS vs,
            LAG(d.close, 1) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date) AS pc
        FROM daily d
        WHERE d.trade_date <= ?
          AND d.trade_date >= CAST(CAST(? AS DATE) - INTERVAL '70 days' AS VARCHAR)
    ),
    f AS (
        SELECT b.ts_code, b.trade_date,
            ((b.close-b.c4)/NULLIF(b.c4,0) - (b.close-b.c6)/NULLIF(b.c6,0))/NULLIF(ABS((b.close-b.c6)/NULLIF(b.c6,0)),0) AS ma,
            SQRT(b.vol/NULLIF(b.vol5,0)) * ((b.close-b.pc)/NULLIF(b.pc,0)) * (1+ABS(((b.close-b.pc)/NULLIF(b.pc,0))*100)/100) AS flow,
            (b.ps/NULLIF(b.pa,0))/NULLIF((b.vs/NULLIF(b.va,0)),0) AS vola,
            CASE WHEN sb.name LIKE '%ST%' OR sb.market='北交所' OR sb.ts_code LIKE '8%' OR sb.ts_code LIKE '4%' THEN 1 ELSE 0 END AS is_bad
        FROM base b LEFT JOIN stock_basic sb ON sb.ts_code=b.ts_code
    )
    SELECT f.ts_code, f.trade_date, f.ma, f.flow, f.vola
    FROM f WHERE f.is_bad=0 AND f.ma IS NOT NULL AND f.flow IS NOT NULL AND f.vola IS NOT NULL
      AND f.trade_date = ?
    """, [d, d_iso, d]).df()
    t.close()
    if df.empty:
        print(f'无数据: {d}'); return
    # 稳健 z（2026-08-08 对齐 fusion_3f 口径）：先按当日 1%-99% 分位截断极端值
    # （ma_decay 分母爆炸离群实测 min=-814, 0.57% 股票/天 → 拉爆当日 std → 正常股票 z 被压扁,
    #   中枢分失去区分度），再算当日截面均值/标准差。与 feat_tushare.compute_norm_stats 同思路。
    for col in ['ma', 'flow', 'vola']:
        lo, hi = df[col].quantile(0.01), df[col].quantile(0.99)
        df[col] = df[col].clip(lo, hi)
        std = df[col].std(ddof=1)
        df[f'{col}_z'] = (df[col] - df[col].mean()) / (std if std > 1e-12 else 1.0)
    df['score'] = -(df['ma_z'].abs() + df['flow_z'].abs() + df['vola_z'].abs())
    df['rank_pct'] = df['score'].rank(pct=True)
    df['signal'] = np.where(df['rank_pct'] >= 0.85, '强买',
                   np.where(df['rank_pct'] >= 0.65, '买',
                   np.where(df['rank_pct'] >= 0.35, '持',
                   np.where(df['rank_pct'] >= 0.15, '卖', '强卖'))))

    td = duckdb.connect(str(TUSHARE_DB), read_only=True)
    names = {r[0].split('.')[0]: (r[1], r[2]) for r in td.execute("SELECT ts_code, name, industry FROM stock_basic").fetchall()}
    td.close()

    s = sqlite3.connect(str(STATE_DB))
    s.execute("""CREATE TABLE IF NOT EXISTS fusion_center_signals (
        date TEXT, stock_code TEXT, stock_name TEXT, industry TEXT,
        score REAL, rank_pct REAL, signal TEXT, PRIMARY KEY (date, stock_code))""")
    s.execute("DELETE FROM fusion_center_signals WHERE REPLACE(date,'-','')=?", (d,))
    rows = [(d, r.ts_code.split('.')[0], (names.get(r.ts_code.split('.')[0]) or ('',''))[0],
             (names.get(r.ts_code.split('.')[0]) or ('',''))[1], round(float(r.score), 4),
             round(float(r.rank_pct), 4), r.signal) for r in df.itertuples()]
    s.executemany("INSERT OR REPLACE INTO fusion_center_signals VALUES (?,?,?,?,?,?,?)", rows)
    s.commit(); s.close()
    dist = df['signal'].value_counts()
    print(f'✅ fusion_center_signals {d}: {len(df):,} 只 | ' + ' '.join(f'{k}{v}' for k, v in dist.items()))
    top = df[df['signal'] == '强买'].nlargest(10, 'score')
    print('强买 top10:')
    for r in top.itertuples():
        nm = (names.get(r.ts_code.split('.')[0]) or ('', ''))[0]
        print(f'  {r.ts_code[:6]} {nm} score={r.score:.3f}')

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
