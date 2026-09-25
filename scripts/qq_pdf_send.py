#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立脚本向主QQ发送 PDF 文件（c2c RichMedia）。
不依赖 gateway 进程：直接走 QQ Bot REST API（token → 内联上传 → media 消息）。
凭据读 config.yaml platforms.qqbot.extra，与 gateway 同源。
09-23 新建：hermes send 的 MEDIA: 路由不支持 qqbot（send_message_tool 文本层限制），
盘后/盘前 PDF 报告推送走本脚本。"""
import asyncio, base64, hashlib, json, os, sys
from pathlib import Path

import httpx

CHAT_ID = "3A9EE9C3C40A3E1DE81CF01F5BC42616"   # 主人 c2c
API = "https://api.sgroup.qq.com"
MEDIA_TYPE_FILE = 4
MSG_TYPE_MEDIA = 7
INLINE_LIMIT = 10_000_000  # ~10MB 以内走内联 base64，超过走分块上传


def _load_creds():
    import yaml
    # 凭据来源1: config.yaml platforms.qqbot.extra；来源2: ~/.hermes/.env 的 QQ_APP_ID/QQ_CLIENT_SECRET
    # （09-23 实测：本机主 qqbot 凭据在 .env，config.yaml platforms: 段只有 qqbot2/3/4）
    cfg = yaml.safe_load(open(os.path.expanduser("~/.hermes/config.yaml")))
    extra = (cfg.get("platforms", {}).get("qqbot", {}) or {}).get("extra", {}) or {}
    app_id, secret = str(extra.get("app_id", "")), extra.get("client_secret", "")
    if not app_id or not secret:
        for line in open(os.path.expanduser("~/.hermes/.env")):
            line = line.strip().removeprefix("export ").strip()
            if line.startswith("QQ_APP_ID="):
                app_id = app_id or line.split("=", 1)[1].strip().strip("'\"")
            elif line.startswith("QQ_CLIENT_SECRET="):
                secret = secret or line.split("=", 1)[1].strip().strip("'\"")
    if not app_id or not secret:
        raise SystemExit("找不到 qqbot 凭据（config.yaml extra 与 .env 均无）")
    return app_id, secret


async def _token(client, app_id, secret):
    r = await client.post("https://bots.qq.com/app/getAppAccessToken",
                          json={"appId": app_id, "clientSecret": secret}, timeout=15)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"get token failed: {r.text[:200]}")
    return tok


async def _inline_upload(client, headers, data, file_name):
    body = {"file_type": MEDIA_TYPE_FILE, "file_name": file_name,
            "file_data": base64.b64encode(data).decode(),
            "srv_send_msg": False}
    r = await client.post(f"{API}/v2/users/{CHAT_ID}/files", headers=headers, json=body, timeout=60)
    j = r.json()
    info = j.get("file_info") or (j.get("data") or {}).get("file_info")
    if not info:
        raise RuntimeError(f"upload 无 file_info: {str(j)[:300]}")
    return info


async def _chunked_upload(client, headers, data, file_name):
    """10MB+ 分块上传（upload_prepare → PUT parts → upload_part_finish → files）。"""
    md5 = hashlib.md5(data).hexdigest()
    md5_10m = hashlib.md5(data[:10_002_432]).hexdigest()
    prep = {"file_type": MEDIA_TYPE_FILE, "file_name": file_name, "file_size": len(data),
            "md5": md5, "md5_10m": md5_10m}
    r = await client.post(f"{API}/v2/users/{CHAT_ID}/upload_prepare", headers=headers, json=prep, timeout=30)
    j = r.json()
    src = j.get("data") if isinstance(j.get("data"), dict) else j
    upload_id = src.get("upload_id")
    if not upload_id:
        raise RuntimeError(f"upload_prepare 失败: {str(j)[:300]}")
    parts = src.get("parts") or src.get("part_list") or []
    seq = 0
    for p in parts:
        url = p.get("presigned_url") or p.get("url")
        idx = int(p.get("part_index") or p.get("index") or 0)
        start = (idx - 1) * int(src.get("block_size", 0)) if src.get("block_size") else 0
        chunk = data[start:start + int(src.get("block_size", len(data)))]
        pr = await client.put(url, content=chunk, timeout=300)
        pr.raise_for_status()
        seq += 1
        fin = await client.post(f"{API}/v2/users/{CHAT_ID}/upload_part_finish", headers=headers,
                                json={"upload_id": upload_id, "part_index": idx, "seq": seq}, timeout=30)
        if fin.status_code != 200:
            raise RuntimeError(f"part_finish {idx} 失败: {fin.text[:200]}")
    r = await client.post(f"{API}/v2/users/{CHAT_ID}/files", headers=headers,
                          json={"upload_id": upload_id, "file_type": MEDIA_TYPE_FILE,
                                "file_name": file_name, "srv_send_msg": False}, timeout=60)
    j = r.json()
    info = j.get("file_info") or (j.get("data") or {}).get("file_info")
    if not info:
        raise RuntimeError(f"complete 无 file_info: {str(j)[:300]}")
    return info


async def send_pdf(path):
    import base64
    path = Path(path).expanduser().resolve()
    data = path.read_bytes()
    app_id, secret = _load_creds()
    async with httpx.AsyncClient() as client:
        tok = await _token(client, app_id, secret)
        headers = {"Authorization": f"QQBot {tok}", "Content-Type": "application/json"}
        if len(data) <= INLINE_LIMIT:
            info = await _inline_upload(client, headers, data, path.name)
        else:
            info = await _chunked_upload(client, headers, data, path.name)
        import time as _t, uuid as _uuid
        seq = (int(_t.time()) % 100000000 ^ int(_uuid.uuid4().hex[:4], 16)) % 65536 or 1
        body = {"msg_type": MSG_TYPE_MEDIA, "content": "",
                "media": {"file_info": info}, "msg_seq": seq}
        r = await client.post(f"{API}/v2/users/{CHAT_ID}/messages", headers=headers, json=body, timeout=30)
        j = r.json()
        if r.status_code != 200 or j.get("message") and not j.get("id"):
            raise RuntimeError(f"send 失败 {r.status_code}: {str(j)[:300]}")
        return j.get("id") or "ok"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: send_qq_pdf.py <pdf路径>")
    mid = asyncio.run(send_pdf(sys.argv[1]))
    print(f"PDF 发送: ok (message_id={mid})")
