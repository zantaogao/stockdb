#!/usr/bin/env python3
from core import db
c = db._safe_connect('state.db', read_only=True)
n = c.execute("SELECT COUNT(*) FROM signal_history WHERE date='2026-07-22'").fetchone()[0]
print(f"今日已写入：{n}条")
c.close()
