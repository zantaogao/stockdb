#!/usr/bin/env python3
"""测当前主模型(mlx-serve :11234) decode 速度: 短/30K/60K 三档"""
import json, time, urllib.request

URL = "http://127.0.0.1:11234/v1/chat/completions"

def test(nrep, label, ntok=200):
    prompt = "测试" * nrep + "\n请用一句话总结以上内容。"
    body = json.dumps({
        "model": "Qwen3.8-Flash-Next-Uncensored-MLX-Serve-4bit",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": ntok, "temperature": 0.5, "stream": False
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=600).read())
    except Exception as e:
        print(f"{label}: 失败 {e}", flush=True); return
    dt = time.time() - t0
    u = resp.get("usage", {})
    pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    # TTFT via stream
    t1 = time.time()
    sbody = json.dumps({
        "model": "Qwen3.8-Flash-Next-Uncensored-MLX-Serve-4bit",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": ntok, "temperature": 0.5, "stream": True
    }).encode()
    sreq = urllib.request.Request(URL, data=sbody, headers={"Content-Type": "application/json"})
    first = None; got = 0
    with urllib.request.urlopen(sreq, timeout=600) as r:
        for line in r:
            if line.startswith(b"data:"):
                if first is None: first = time.time() - t1
                got += 1
    if first and got > 1:
        decode = (got - 1) / (time.time() - t1 - first)
        print(f"{label}: prompt={pt}tok TTFT={first:.1f}s decode={decode:.1f}t/s", flush=True)
    else:
        print(f"{label}: prompt={pt}tok 生成={ct}tok 总{dt:.1f}s (流式失败)", flush=True)

# 预热一次(排除冷启动)
test(50, "warmup", 50)
test(50, "短prompt(基线)")
test(15000, "~30K")
test(30000, "~60K")