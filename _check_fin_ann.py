"""查 fin 表 ann_date 现状（决定跳过策略）"""
import duckdb

db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for table in ['fin_income', 'fin_balancesheet', 'fin_cashflow']:
    try:
        cols = [c[0] for c in db.execute(f'DESCRIBE {table}').fetchall()]
        has_ann = 'ann_date' in cols
        if has_ann:
            r = db.execute(f'SELECT MAX(ann_date), MAX(end_date) FROM {table}').fetchone()
            print(f'{table}: MAX(ann_date)={r[0]}, MAX(end_date)={r[1]}')
        else:
            print(f'{table}: 无 ann_date 列, 列={cols[:12]}')
    except Exception as e:
        print(f'{table}: {e}')
db.close()
