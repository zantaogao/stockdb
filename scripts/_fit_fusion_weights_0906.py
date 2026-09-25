import sqlite3, numpy as np, pandas as pd
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
df = pd.read_sql("SELECT date,reg10,reg20,reg40,fusion_score FROM signal_history "
                 "WHERE reg10 IS NOT NULL AND reg20 IS NOT NULL AND reg40 IS NOT NULL "
                 "AND fusion_score IS NOT NULL", con)
print('行数', len(df), df['date'].min(), '~', df['date'].max())
for d in sorted(df['date'].unique())[::max(1, len(df['date'].unique())//12)]:
    sub = df[df['date'] == d]
    if len(sub) < 100:
        print(d, '样本少', len(sub)); continue
    X = sub[['reg10', 'reg20', 'reg40']].to_numpy(float)
    y = sub['fusion_score'].to_numpy(float)
    ok = np.isfinite(X).all(axis=1) * np.isfinite(y)
    X, y = X[ok], y[ok]
    Xs = (X - X.mean(0)) / (X.std(0) + 1e-12)
    ys = (y - y.mean()) / (y.std() + 1e-12)
    w = np.linalg.lstsq(Xs, ys, rcond=None)[0]
    r2 = 1 - ((ys - Xs @ w) ** 2).sum() / (ys ** 2).sum()
    print(d, '标准化权重 w10/w20/w40 =', np.round(w, 3), ' R2 =', round(r2, 4))