import baostock as bs, warnings
warnings.filterwarnings("ignore")
lg = bs.login()
print("login:", lg.error_code, lg.error_msg)
rs = bs.query_history_k_data_plus(
    "sh.603257", "date,time,open,high,low,close,volume",
    start_date="2024-01-01", end_date="2026-09-04",
    frequency="5", adjustflag="3")
rows = []
while rs.error_code == "0" and rs.next():
    rows.append(rs.get_row_data())
print("5min error:", rs.error_code, rs.error_msg, "rows:", len(rows))
if rows:
    print("range:", rows[0][1], "->", rows[-1][1])
bs.logout()