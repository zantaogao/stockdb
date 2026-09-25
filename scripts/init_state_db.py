import duckdb
import os

db_path = '/Users/zantao/.hermes/stockdb/state.db'

def init_db():
    try:
        conn = duckdb.connect(db_path)
        # 1. 观察名单表
        conn.execute('CREATE TABLE IF NOT EXISTS watchlist (ts_code VARCHAR PRIMARY KEY, score DOUBLE, scan_date DATE, status VARCHAR, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        # 2. 交易信号表
        conn.execute('CREATE TABLE IF NOT EXISTS trade_signals (signal_id VARCHAR PRIMARY KEY, ts_code VARCHAR, direction VARCHAR, price DOUBLE, quantity INTEGER, signal_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status VARCHAR)')
        # 3. 执行流水表
        conn.execute('CREATE TABLE IF NOT EXISTS execution_logs (exec_id VARCHAR PRIMARY KEY, signal_id VARCHAR, ts_code VARCHAR, direction VARCHAR, exec_price DOUBLE, exec_quantity INTEGER, exec_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status VARCHAR, error_msg VARCHAR)')
        # 4. 模型性能表 (IC监控)
        conn.execute('CREATE TABLE IF NOT EXISTS model_performance (id INTEGER PRIMARY KEY, date DATE, model_id VARCHAR, ic_value DOUBLE, rank_ic DOUBLE, ir DOUBLE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        conn.close()
        print(f"SUCCESS: {db_path} initialized with 4 tables.")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == '__main__':
    init_db()
