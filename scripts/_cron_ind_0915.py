# -*- coding: utf-8 -*-
import duckdb, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
codes = {'601615': '明阳智能', '688186': '广大特材', '301662': '宏工科技', '001332': '锡装股份',
         '301186': '超达装备', '603090': '宏盛股份', '002865': '钧达股份', '603381': '永臻股份',
         '688560': '明冠新材', '301500': '飞南资源', '002491': '通鼎互联', '603186': '华正新材',
         '300658': '延江股份', '688093': '世华科技', '688191': '智洋创新', '301283': '聚胶股份'}
for c, nm in codes.items():
    ts = c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ')
    r = con.execute("SELECT industry, market FROM stock_basic WHERE ts_code=?", (ts,)).fetchone()
    print(f"  {c} {nm:<7} {r}")
con.close()
