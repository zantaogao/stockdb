"""Restore server_dashboard.py from .bak and fix triple-quote issue"""
import re

with open('/Users/zantao/.hermes/stockdb/server_dashboard.py.bak', 'r') as f:
    content = f.read()

# Remove line number prefixes
content = re.sub(r'^\s*\d+\|', '', content, flags=re.MULTILINE)

# Find and fix the triple-quoted f-string issue
# The problem: 
#   rows = conn.execute(f"""
#       SELECT ...
#       FROM daily WHERE ts_code='{code}'
#   """).fetchall()
# After line-number removal becomes just the SELECT/FROM lines.
# We need to close the triple-quote

# Find the unclosed f-string
target = "FROM daily WHERE ts_code='{code}'"
if target in content:
    # Replace everything from the open quote to the end
    # Actually, the real issue is what comes after the target
    idx = content.find(target) + len(target)
    after = content[idx:idx+30]
    print(f"After target: {repr(after)}")
    
    if not after.lstrip().startswith('"""'):
        # Need to close the triple-quote
        # Close it after the FROM line
        closing = '\n        """).fetchall()\n\n        if len(rows) < 5:\n            conn.close()\n            self._json({"error": "日线不足"})\n            return'
        content = content[:idx] + closing + content[idx:]

# Remove the duplicate etf-list handler if it got duplicated
# (the .bak might have a duplicate from earlier edits)
# Find the class definition and ensure everything is properly structured

with open('/Users/zantao/.hermes/stockdb/server_dashboard.py', 'w') as f:
    f.write(content)
print("Saved")
