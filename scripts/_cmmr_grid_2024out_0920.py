# -*- coding: utf-8 -*-
import pandas as pd
c = pd.read_csv('/Users/zantao/.hermes/stockdb/analysis/cmmr_grid_days/2024.csv')
c = c[c.w == '40/40/20'].copy(); c['date'] = c['date'].astype(int)
print(c[['pool_n','ex']].describe().round(4).to_string())
print(c.sort_values('ex').head(3).to_string())
print(c.sort_values('ex').tail(3).to_string())
d = c.set_index('date').ex
print('2024-09-24前后:', d.loc[20240920:20240930].round(2).to_string() if 20240920 in d.index else 'n/a')
