#!/usr/bin/env python3
import re, html

def extract(path):
    raw = open(path, encoding='utf-8', errors='ignore').read()
    raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text

t = extract('/tmp/jlkj_caifuhao.html')
i = t.find('杰理科技')
if i >= 0:
    seg = t[max(0, i-300): i+4500]
    # 截断到明显噪音处
    for kw in ['免责声明', '风险提示', '来源', '东方财富', '本文']:
        j = seg.find(kw)
        if j > 2000:
            seg = seg[:j]
            break
    print(seg)
