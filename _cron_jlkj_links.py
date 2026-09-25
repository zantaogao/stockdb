#!/usr/bin/env python3
import re, html
raw = open('/tmp/jlkj_bing2.html', encoding='utf-8', errors='ignore').read()
# 提取所有链接及其标题
links = re.findall(r'<a[^>]+href="(http[^"]+)"[^>]*>(.*?)</a>', raw, flags=re.S)
seen = set()
for url, title in links:
    t = re.sub(r'<[^>]+>', '', title)
    t = html.unescape(t).strip()
    if not t or '杰理' not in t:
        continue
    if 'bing' in url or 'baidu' in url or 'microsoft' in url:
        continue
    # 解码bing跳转链接
    m = re.search(r'[?&]u=a1([^&]+)', url)
    if m:
        import urllib.parse
        url = urllib.parse.unquote(m.group(1))
    if url in seen:
        continue
    seen.add(url)
    print(t, '=>', url)
