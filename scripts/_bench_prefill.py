#!/usr/bin/env python3
"""冷prefill基准：拼一个无缓存的大prompt，打两次（第2次测缓存命中），读mlx-serve日志报tok/s"""
import json, time, urllib.request, hashlib

words = " ".join(f"词{hashlib.md5(str(i).encode()).hexdigest()[:6]}" for i in range(6000))
for run in range(2):
    payload = {"model": "default",
               "messages": [{"role": "user", "content": words + "\n回答：好"}],
               "max_tokens": 5, "temperature": 0}
    req = urllib.request.Request('http://127.0.0.1:11234/v1/chat/completions',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=600))
    dt = time.time() - t0
    print(f"run{run+1}: prompt={r.get('usage',{}).get('prompt_tokens')} 总耗时={dt:.1f}s", flush=True)