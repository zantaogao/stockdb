#!/usr/bin/env python3
"""补测: warm 后真实基线 + 不同前缀 90K(无 cache 命中) 的生成速度"""
import json
import time
import urllib.request

URL = "http://127.0.0.1:8082/completion"


def test(prompt, label):
    body = json.dumps({
        "prompt": prompt, "max_tokens": 200, "stream": False, "temperature": 0.5
    }).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=900).read())
    except Exception as e:
        print(f"{label}: 失败 {e}")
        return
    dt = time.time() - t0
    t = resp.get("timings", {})
    n_tok = resp.get("tokens_predicted", 0)
    print(f"{label}: prefill={t.get('prompt_per_second', 0):.1f} t/s "
          f"gen={t.get('predicted_per_second', 0):.1f} t/s "
          f"({n_tok} tok, 总 {dt:.0f}s)", flush=True)


print("=== 补测(warm 后) ===", flush=True)
test("你好", "baseline-warm(KV<1K)")
test("市场" * 45000, "90K-无缓存(不同前缀)")
print("=== 完成 ===", flush=True)
