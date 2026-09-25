"""Fix truncated server_dashboard.py"""
import re

with open('/Users/zantao/.hermes/stockdb/server_dashboard.py', 'r') as f:
    content = f.read()

# Find the broken query ending
old = '            FROM daily WHERE ts_code=\'{\'code\'}\''
# The issue is simpler - the file has literal broken content at the end
# Just trim back to last complete line

lines = content.split('\n')
# Remove incomplete query
for i in range(len(lines)-1, -1, -1):
    if 'def main():' in lines[i]:
        # File has main() intact
        break
    if 'FROM daily WHERE' in lines[i] and 'fetchall' not in content[content.rfind('pct_chg, vol, amount'):]:
        # This is the broken query - remove all incomplete lines from here
        content = '\n'.join(lines[:i])
        break

# Add back code to close the function and complete the file
content += '''

        conn.close()
        self._json({"error": "数据不足"})
    
    def log_message(self, fmt, *args):
        pass


def main():
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 8081), DashboardHandler)
    print("Dashboard running on :8081")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
'''

with open('/Users/zantao/.hermes/stockdb/server_dashboard.py', 'w') as f:
    f.write(content)
print('Fixed')
