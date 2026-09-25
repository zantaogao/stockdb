# -*- coding: utf-8 -*-
"""定位 kyle/amihud 对拍差异票：新库逐票 vs 发现cache"""
import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
import numpy as np, pandas as pd
import micro_feat_lib

if __name__ == '__main__':
    new = micro_feat_lib.micro_feats_for_date('20260918')
    old = pd.read_parquet('/Users/zantao/.hermes/stockdb/analysis/micro_feats_daily_0919.parquet')
    old['code'] = old['ts_code'].str.split('.').str[-1].str.zfill(6)
    old = old[old['trade_date'] == '20260918']
    j = new.merge(old[['code', 'kyle', 'amihud']], on='code', suffixes=('_new', '_old'))
    j['dk'] = (j.kyle_new - j.kyle_old).abs()
    j['da'] = ((j.amihud_new - j.amihud_old) / j.amihud_old.clip(lower=1e-12)).abs()
    bad = j[(j.dk > 0.01) | (j.da > 0.001)].sort_values('dk', ascending=False)
    print('差异票数', len(bad), '/', len(j))
    print(bad.head(6)[['code', 'kyle_new', 'kyle_old', 'amihud_new', 'amihud_old']].to_string(index=False))
    # 看最大差票的分钟数据条数与首尾bar
    if len(bad):
        c = bad.iloc[0]['code']
        for pfx in ('sh', 'sz'):
            try:
                d = pd.read_parquet(f'/Users/zantao/.hermes/stockdb/minutes/5min/{pfx}_{c}.parquet')
            except FileNotFoundError:
                continue
            d = d[d['date'].astype(str) == '2026-09-18']
            print(c, pfx, 'bars', len(d), 'vol=0条数', int((d['volume'] == 0).sum()))
            print(d[['time', 'close', 'volume', 'amount']].head(3).to_string(index=False))
            break
