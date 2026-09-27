"""v8上线后每日回归检查: 当日新分数 vs 前一交易日分布漂移粗检(均值偏移>3σ日间 或 std翻倍 → 告警).
判据基于 signal_history(列: reg10_pred/reg40_pred/fusion_score).
"""
import sys, sqlite3
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path.home()/'.hermes/stockdb'
con = sqlite3.connect(BASE/'signals.db')
days = [r[0] for r in con.execute("SELECT DISTINCT date FROM signal_history ORDER BY date DESC LIMIT 2").fetchall()]
last, prev_d = days[0], days[1]
df = pd.read_sql("SELECT reg10_pred, reg40_pred, fusion_score FROM signal_history WHERE date=?", con, params=[last])
prev = pd.read_sql("SELECT reg10_pred, reg40_pred, fusion_score FROM signal_history WHERE date=?", con, params=[prev_d])
con.close()
if len(df) < 4000:
    print(f"⚠️ {last} 仅{len(df)}票(应≥4900), 打分链路可能未跑完")
ok = True
for col in ['reg10_pred','reg40_pred','fusion_score']:
    a = df[col].astype(float); b = prev[col].astype(float)
    shift = abs(a.mean()-b.mean()); z_thr = 3*b.std()/max(len(a),1)**0.5
    flag = '⚠️' if (shift > z_thr or a.std() > 2.5*b.std()) else '✓'
    if flag == '⚠️': ok = False
    print(f"{flag} {col}: {last} mean={a.mean():.2f} std={a.std():.2f} | {prev_d} mean={b.mean():.2f} std={b.std():.2f}")
print(f"检查日={last} 票数={len(df)} 结论={'正常' if ok else '需人工复核'}")
sys.exit(0 if ok else 2)
