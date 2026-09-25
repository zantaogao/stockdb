#!/usr/bin/env python3
"""独立发送本地文件到 QQ c2c（upload + rich media），绕开 send_message 的纯文本路由。"""
import asyncio, base64, hashlib, json, sys
from pathlib import Path
import httpx

import yaml
_cfg = yaml.safe_load(open(Path.home() / ".hermes/config.yaml"))
_pf = _cfg["qqbot"]["extra"]   # 主QQ（小A助手），配置在顶层
APP_ID = str(_pf["app_id"])
SECRET = _pf["client_secret"]
CHAT = "3A9EE9C3C40A3E1DE81CF01F5BC42616"

FILE = sys.argv[1]
CAPTION = sys.argv[2] if len(sys.argv) > 2 else Path(FILE).name

async def main():
    path = Path(FILE)
    data = path.read_bytes()
    async with httpx.AsyncClient(timeout=60) as c:
        tok = (await c.post("https://bots.qq.com/app/getAppAccessToken",
                            json={"appId": APP_ID, "clientSecret": SECRET})).json()["access_token"]
        h = {"Authorization": f"QQBot {tok}"}
        url = f"https://api.sgroup.qq.com/v2/users/{CHAT}/files"
        body = {
            "file_type": 4,
            "file_name": path.name,
            "file_data": base64.b64encode(data).decode(),
            "file_sha": hashlib.md5(data).hexdigest(),
            "srv_send_msg": False,
        }
        up = (await c.post(url, json=body, headers=h)).json()
        print("upload:", json.dumps(up, ensure_ascii=False)[:300])
        file_info = (up.get("data") or {}).get("file_info") or up.get("file_info")
        if not file_info:
            sys.exit("no file_info")
        msg = {"content": CAPTION[:4000], "msg_type": 7,
               "media": {"file_info": file_info}, "msg_seq": 92301}
        send = (await c.post(f"https://api.sgroup.qq.com/v2/users/{CHAT}/messages",
                             json=msg, headers=h)).json()
        print("send:", json.dumps(send, ensure_ascii=False)[:300])

asyncio.run(main())
