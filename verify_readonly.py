
from core.db import get_tushare_db
import duckdb

try:
    print("Attempting to write to tushare.db via get_tushare_db()...")
    conn = get_tushare_db()
    # 尝试创建一个表，如果处于 read_only=True 模式，这应该会失败
    conn.execute("CREATE TABLE readonly_test (id INTEGER)")
    print("Error: Write succeeded! The DB is NOT read-only.")
except Exception as e:
    print(f"Success: Caught expected error: {e}")
finally:
    try:
        conn.close()
    except:
        pass
