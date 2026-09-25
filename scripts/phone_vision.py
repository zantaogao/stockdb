#!/usr/bin/env python3
"""截屏 + 直接喂本地 mlx-serve 看图（vision_analyze 工具通道对该模型空回复，直连API正常）
用法: phone_vision.py [问题]"""
import base64, json, subprocess, sys, urllib.request

q = sys.argv[1] if len(sys.argv) > 1 else "这是什么页面？描述关键元素和大致坐标。"
subprocess.run(['adb', 'exec-out', 'screencap', '-p'], stdout=open('/tmp/pv.png', 'wb'), check=True)
img = base64.b64encode(open('/tmp/pv.png', 'rb').read()).decode()
payload = {
    "model": "default",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": q + " 屏幕原图1260x2800，坐标按原图给。"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]}],
    "max_tokens": 300,
}
req = urllib.request.Request('http://127.0.0.1:11234/v1/chat/completions',
    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
r = json.load(urllib.request.urlopen(req, timeout=180))
print(r['choices'][0]['message']['content'])