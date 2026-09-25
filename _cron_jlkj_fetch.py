#!/usr/bin/env python3
"""下载并提取文章正文"""
import re, html, urllib.request, sys

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

def fetch(url, out):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read().decode('utf-8', errors='ignore')
    open(out, 'w', encoding='utf-8').write(data)
    print(f"{out}: {len(data)} bytes")

def extract(path):
    raw = open(path, encoding='utf-8', errors='ignore').read()
    raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text

urls = {
    '/tmp/jlkj_ifeng.html': 'https://finance.ifeng.com/c/8vH6rIkjlTn',
    '/tmp/jlkj_caifuhao.html': 'https://caifuhao.eastmoney.com/news/20260730190015690273260',
}
for path, url in urls.items():
    try:
        fetch(url, path)
    except Exception as e:
        print(f"{url} 失败: {e}")

# 提取凤凰正文
try:
    t = extract('/tmp/jlkj_ifeng.html')
    # 凤凰正文一般在特定 div，取全文然后截取杰理相关
    i = t.find('杰理科技')
    if i >= 0:
        print("\n===== 凤凰财经 =====")
        print(t[max(0,i-200): i+4000])
except Exception as e:
    print("ifeng 解析失败:", e)
