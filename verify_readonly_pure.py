
import duckdb
from pathlib import Path

db_path = Path.home() / '.hermes' / 'stockdb' / 'tushare.db'

try:
    print(f"Testing read-only access to: {db_path}")
    # 模拟 core.db.get_tushare_db() 的核心行为
    conn = duckdb.connect(str(db_path), read_only=True)
    
    print("Attempting to create a table in read-only mode...")
    conn.execute("CREATE TABLE readonly_verify_test (id INTEGER)")
    print("FAILED: Write succeeded! DB is not read-only.")
except Exception as e:
    print(f"SUCCESS: Caught expected error: {e}")
finally:
    try:
        conn.close()
    except:
        pass
