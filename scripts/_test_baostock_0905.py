#!/usr/bin/env python3
# 测 baostock 5min 数据可得性：能否拉到 2026-09-05（周五）的分钟线
import baostock as bs
lg = bs.login()
print('login', lg.error_code, lg.error_msg)
for code in ['sh.600000', 'sz.000001']:
    rs = bs.query_history_k_data_plus(code, 'date,time,close,volume',
        start_date='2026-09-04', end_date='2026-09-05', frequency='5', adjustflag='3')
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    dates = sorted({r[0] for r in rows})
    print(code, 'rows', len(rows), 'dates', dates)
bs.logout()