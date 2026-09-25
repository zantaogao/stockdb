import duckdb
from datetime import date
c = duckdb.connect('state.db')
today = date.today().isoformat()

# 统计信息
total = c.execute(f"SELECT COUNT(*) FROM signal_history WHERE date='{today}'").fetchone()[0]
high = c.execute(f"SELECT COUNT(*) FROM signal_history WHERE date='{today}' AND fusion_score >= 80").fetchone()[0]
med = c.execute(f"SELECT COUNT(*) FROM signal_history WHERE date='{today}' AND fusion_score >= 60 AND fusion_score < 80").fetchone()[0]
low = c.execute(f"SELECT COUNT(*) FROM signal_history WHERE date='{today}' AND fusion_score < 60").fetchone()[0]

print(f'📊 全量选股评分完成 - {today}')
print(f'='*50)
print(f'总股票数：{total}')
print(f'🟢 高分 (≥80): {high}')
print(f'🟡 中分 (60-79): {med}')
print(f'🔴 低分 (<60): {low}')
print()
print('Top 5 推荐股票:')
rows = c.execute(f"SELECT stock_code, stock_name, fusion_score, reg40_pred FROM signal_history WHERE date='{today}' ORDER BY fusion_score DESC LIMIT 5").fetchall()
for r in rows:
    print(f'  {r[0]} {r[1]} 融合分={r[2]} 40d 预测={r[3]:+.2f}%')
