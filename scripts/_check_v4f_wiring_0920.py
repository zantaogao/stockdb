# -*- coding: utf-8 -*-
"""v4f 影子链对拍（2026-09-20）：micro_feat_lib 新库 vs 发现轮 cache（micro_feats_daily_0919）"""
import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
import pandas as pd
import micro_feat_lib

if __name__ == '__main__':
    new = micro_feat_lib.micro_feats_for_date('20260918')
    old = pd.read_parquet('/Users/zantao/.hermes/stockdb/analysis/micro_feats_daily_0919.parquet')
    old['code'] = old['ts_code'].str.split('.').str[-1].str.zfill(6)
    old = old[old['trade_date'] == '20260918']
    j = new.merge(old[['code', 'kyle', 'amihud']], on='code', suffixes=('_new', '_old'))
    print('对拍票数', len(j),
          ' kyle最大abs差', float((j.kyle_new - j.kyle_old).abs().max()),
          ' amihud最大rel差', float(((j.amihud_new - j.amihud_old) / j.amihud_old).abs().max()))
