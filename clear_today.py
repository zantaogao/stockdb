#!/usr/bin/env python3
from core import db
c = db._safe_connect('state.db', read_only=False)
c.execute("DELETE FROM signal_history WHERE date='2026-07-22'")
c.execute('CHECKPOINT')
c.close()
print("已清空 2026-07-22 的数据")
