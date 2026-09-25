#!/usr/bin/env python3
import re, html
raw = open('/tmp/jlkj_bing2.html', encoding='utf-8', errors='ignore').read()
raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.S)
text = re.sub(r'<[^>]+>', ' ', raw)
text = html.unescape(text)
text = re.sub(r'\s+', ' ', text)
# 找含"杰理科技"的片段
hits = 0
for m in re.finditer(r'杰理科技', text):
    s = max(0, m.start()-200); e = min(len(text), m.end()+300)
    print('...', text[s:e], '...')
    print('---')
    hits += 1
    if hits >= 12:
        break
print(f"共 {hits} 处")
