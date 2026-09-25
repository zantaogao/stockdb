import duckdb
c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for t in ['forecast','repurchase','pledge_stat','broker_recommend','dividend','stk_holdernumber','top10_holders','top10_floatholders','stock_valuation','money_flow','stk_limit']:
    try:
        cols = [r[0] for r in c.execute(f"describe {t}").fetchall()]
        n = c.execute(f"select count(*) from {t}").fetchone()[0]
        print('###', t, 'rows=', n)
        print('   cols:', cols)
    except Exception as e:
        print('###', t, 'ERR', str(e)[:120])
# coverage / freshness of event tables
for t, dcol in [('forecast','ann_date'),('repurchase','ann_date'),('pledge_stat','end_date'),('stk_holdernumber','ann_date'),('broker_recommend','report_date')]:
    try:
        row = c.execute(f"select min({dcol}), max({dcol}), count(distinct {dcol}) from {t}").fetchone()
        print('COV', t, row)
    except Exception as e:
        print('COV', t, 'ERR', str(e)[:120])
