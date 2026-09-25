"""统计近一周行业表现：电力行业是不是真的最亮"""
import duckdb
from datetime import datetime, timedelta

conn = duckdb.connect('/Users/zantao/.hermes/stockdb/stock.db', read_only=True)
today = '2026-05-30'

# 最近5个交易日
dates = conn.execute(f"""
    SELECT DISTINCT date FROM stock_daily 
    WHERE date <= '{today}' ORDER BY date DESC LIMIT 7
""").fetchall()
date_list = [str(r[0]) for r in dates]
print(f'最近交易日: {date_list}')

week_ago = date_list[4] if len(date_list) >= 5 else date_list[-1]
end = date_list[0]

# 各行业近5日涨幅（等权平均）
rows = conn.execute(f"""
    WITH start_prices AS (
        SELECT stock_code, close as start_close
        FROM stock_daily WHERE date = '{week_ago}'
    ),
    end_prices AS (
        SELECT stock_code, close as end_close
        FROM stock_daily WHERE date = '{end}'
    )
    SELECT s.industry,
           COUNT(*) as stock_count,
           AVG((e.end_close - p.start_close) / p.start_close * 100) as avg_return,
           SUM(CASE WHEN (e.end_close - p.start_close) / p.start_close > 0 THEN 1 ELSE 0 END) as up_count
    FROM stock_info s
    JOIN start_prices p ON s.stock_code = p.stock_code
    JOIN end_prices e ON s.stock_code = e.stock_code
    WHERE s.industry IS NOT NULL AND s.industry != ''
      AND p.start_close > 0 AND e.end_close > 0
    GROUP BY s.industry
    HAVING COUNT(*) >= 5
    ORDER BY avg_return DESC
    LIMIT 20
""").fetchall()

print(f'\n📊 行业近5日表现（{week_ago} → {end}）')
print('=' * 70)
print(f'{"排名":<4} {"行业":<32} {"涨幅":<10} {"上涨比":<10} {"数量"}')
print('-' * 70)
for i, (ind, cnt, ret, up) in enumerate(rows, 1):
    up_pct = up/cnt*100
    bar = '█' * int(up_pct/10) + '░' * (10 - int(up_pct/10))
    print(f'{i:<4} {ind:<32} {ret:>+6.2f}%   {bar} {up}/{cnt}')

# 电力板块权重分析
print(f'\n📋 D44电力行业权重股近5日表现')
power_rows = conn.execute(f"""
    WITH start_p AS (
        SELECT stock_code, close as sc FROM stock_daily WHERE date = '{week_ago}'
    ),
    end_p AS (
        SELECT stock_code, close as ec FROM stock_daily WHERE date = '{end}'
    )
    SELECT i.stock_code, i.stock_name, p.sc, e.ec, 
           (e.ec - p.sc) / p.sc * 100 as ret
    FROM stock_info i
    JOIN start_p p ON i.stock_code = p.stock_code
    JOIN end_p e ON i.stock_code = e.stock_code
    WHERE i.industry LIKE '%电力%' AND p.sc > 0 AND e.ec > 0
    ORDER BY i.stock_code
""").fetchall()

power_up = sum(1 for r in power_rows if r[4] > 0)
power_avg = sum(r[4] for r in power_rows) / len(power_rows)
power_up_pct = power_up / len(power_rows) * 100
print(f'电力板块共{len(power_rows)}只，上涨{power_up}只({power_up_pct:.0f}%)，等权平均{power_avg:+.2f}%')
print()
# Top 5
power_rows.sort(key=lambda x: -x[4])
for code, name, sc, ec, ret in power_rows[:5]:
    print(f'  {name}({code}): {sc:.2f} → {ec:.2f}  {ret:>+6.2f}%')
# Bottom 5
print('  ...')
for code, name, sc, ec, ret in power_rows[-5:]:
    print(f'  {name}({code}): {sc:.2f} → {ec:.2f}  {ret:>+6.2f}%')

# 全市场对比
all_avg = conn.execute(f"""
    SELECT AVG((e.end_close - p.start_close) / p.start_close * 100)
    FROM (SELECT stock_code, close as start_close FROM stock_daily WHERE date = '{week_ago}') p
    JOIN (SELECT stock_code, close as end_close FROM stock_daily WHERE date = '{end}') e
    ON p.stock_code = e.stock_code
    WHERE p.start_close > 0 AND e.end_close > 0
""").fetchall()[0][0]
print(f'\n全市场等权平均: {all_avg:+.2f}%')

# 大盘指数
for idx_name, idx_code in [('上证指数','000001'), ('深证成指','399001')]:
    row = conn.execute(f"""
        SELECT date, close FROM stock_daily 
        WHERE stock_code = '{idx_code}' AND date IN ('{week_ago}', '{end}')
        ORDER BY date
    """).fetchall()
    if len(row) == 2:
        ret = (row[1][1]-row[0][1])/row[0][1]*100
        print(f'{idx_name}: {row[0][1]:.2f} → {row[1][1]:.2f}  {ret:+.2f}%')

# 电力板块候选在新旧阈值下对比
print(f'\n📋 电力板块符合旧阈值(ROE>10) vs 新阈值(ROE>5)')
old_power = conn.execute(f"""
    SELECT COUNT(*) FROM (
        SELECT f.roe FROM stock_info s
        JOIN (SELECT stock_code, close FROM stock_daily WHERE date='{end}') t ON s.stock_code = t.stock_code
        JOIN (SELECT stock_code, AVG(close) as ma60 FROM stock_daily 
              WHERE date >= DATE '{end}' - INTERVAL '60' DAY AND date <= '{end}' GROUP BY stock_code) m ON t.stock_code = m.stock_code
        LEFT JOIN (SELECT stock_code, roe FROM fin_income 
                   WHERE (stock_code, report_date) IN (SELECT stock_code, MAX(report_date) FROM fin_income GROUP BY stock_code)) f ON t.stock_code = f.stock_code
        WHERE s.industry LIKE '%电力%' AND t.close > m.ma60 AND f.roe > 10
    )
""").fetchall()[0][0]

new_power = conn.execute(f"""
    SELECT COUNT(*) FROM (
        SELECT f.roe FROM stock_info s
        JOIN (SELECT stock_code, close FROM stock_daily WHERE date='{end}') t ON s.stock_code = t.stock_code
        JOIN (SELECT stock_code, AVG(close) as ma60 FROM stock_daily
              WHERE date >= DATE '{end}' - INTERVAL '60' DAY AND date <= '{end}' GROUP BY stock_code) m ON t.stock_code = m.stock_code
        LEFT JOIN (SELECT stock_code, roe FROM fin_income
                   WHERE (stock_code, report_date) IN (SELECT stock_code, MAX(report_date) FROM fin_income GROUP BY stock_code)) f ON t.stock_code = f.stock_code
        WHERE s.industry LIKE '%电力%' AND t.close > m.ma60 AND f.roe > 5
    )
""").fetchall()[0][0]
print(f'  旧阈值(ROE>10+站MA60): {old_power}只')
print(f'  新阈值(ROE>5+站MA60):  {new_power}只')

conn.close()
