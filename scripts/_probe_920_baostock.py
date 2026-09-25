
import baostock as bs
lg=bs.login(); print('login', lg.error_code, lg.error_msg)
rs=bs.query_history_k_data_plus("sz.920000","date,time,code,close",frequency="5",start_date="2026-09-01",end_date="2026-09-24")
print('920000 err=',rs.error_code, rs.error_msg)
n=0
while rs.error_code=='0' and rs.next(): n+=1
print('920000 rows=',n)
rs2=bs.query_history_k_data_plus("sh.600000","date,time,code,close",frequency="5",start_date="2026-09-01",end_date="2026-09-24")
n2=0
while rs2.error_code=='0' and rs2.next(): n2+=1
print('600000 rows=',n2,'err=',rs2.error_code)
bs.logout()
