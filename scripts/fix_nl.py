"""Fix \n issue in server_dashboard.py"""
import re
with open('/Users/zantao/.hermes/stockdb/server_dashboard.py', 'r') as f:
    content = f.read()

# Replace the broken line
# The current content has a literal newline inside "..." which is broken
old = 'report = "' + '\n' + '".join(rp)'
new = 'report = "\\n".join(rp)'

content = content.replace(old, new)
with open('/Users/zantao/.hermes/stockdb/server_dashboard.py', 'w') as f:
    f.write(content)
print('Fixed')
