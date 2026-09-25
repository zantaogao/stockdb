#!/usr/bin/env python3
"""实测 35B (qwen3.6-35b-mtp Q6_K, M5 Max) 不同 KV cache 大小下的生成速度
三个档位: 短prompt(基线) / ~30K / ~60K, 各生成 200 tokens 测 predicted_per_second
"""
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
    print(f"{label}: prompt~{len(prompt)//1}字 "
          f"prefill={t.get('prompt_per_second', 0):.1f} t/s "
          f"gen={t.get('predicted_per_second', 0):.1f} t/s "
          f"({n_tok} tok, 总 {dt:.0f}s)")


print("=== 35B 掉速实测 (qwen3.6-35b-mtp Q6_K, M5 Max) ===", flush=True)
test("你好", "short(基线, KV<1K)")
test("测试" * 15000, "med(~30K)")
test("测试" * 30000, "long(~60K)")
print("=== 完成 ===", flush=True)
