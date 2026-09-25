#!/usr/bin/env python3
import re, html
raw = open('/tmp/jlkj_bing.html', encoding='utf-8', errors='ignore').read()
raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.S)
text = re.sub(r'<[^>]+>', ' ', raw)
text = html.unescape(text)
text = re.sub(r'\s+', ' ', text)
seen = set()
for m in re.finditer(r'杰理', text):
    s = max(0, m.start()-150); e = min(len(text), m.end()+250)
    seg = text[s:e]
    if seg not in seen:
        seen.add(seg)
        print('...', seg, '...')
        print('---')
