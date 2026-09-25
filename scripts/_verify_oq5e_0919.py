# Wait for download to finish, then verify integrity (sizes vs remote tree, shard count vs index). No runtime tests.
import os, time, json, urllib.request

DLDIR = os.path.expanduser("~/models/Qwen3.8-Flash-Next-Uncensored-oQ5e-mtp")
LOG = "/tmp/dl_oq5e.log"

# 1) wait for the downloader to exit
while True:
    try:
        tail = open(LOG, "rb").read()[-500:].decode(errors="ignore")
    except FileNotFoundError:
        tail = ""
    if "DL_EXIT=" in tail:
        print("downloader log tail:", tail.strip().splitlines()[-3:])
        if "DL_EXIT=0" not in tail:
            print("RESULT: downloader exited nonzero")
        break
    time.sleep(60)

# 2) remote expected sizes
req = urllib.request.Request(
    "https://hf-mirror.com/api/models/mlx-community/Qwen3.8-Flash-Next-Uncensored-oQ5e-mtp/tree/main?recursive=true",
    headers={"User-Agent": "curl/8"})
remote = {x["path"]: x.get("size", 0) for x in json.load(urllib.request.urlopen(req, timeout=30)) if x.get("type") == "file"}

bad = []
missing = []
total = 0
for rel, sz in sorted(remote.items()):
    p = os.path.join(DLDIR, rel)
    if not os.path.exists(p):
        missing.append(rel); continue
    actual = os.path.getsize(p)
    total += actual
    if sz and actual != sz:
        bad.append((rel, sz, actual))

# 3) cross-check shard coverage vs safetensors index
idx = json.load(open(os.path.join(DLDIR, "model.safetensors.index.json")))
shards = set(idx["weight_map"].values())
absent = [s for s in shards if not os.path.exists(os.path.join(DLDIR, s))]
print(f"files expected={len(remote)} local={len(remote)-len(missing)} bytes={total/1e9:.2f}GB")
print("missing:", missing[:10])
print("size mismatch:", bad[:10])
print("index shards:", len(shards), "absent:", absent)
print("RESULT:", "OK — complete and byte-size verified" if not (missing or bad or absent) else "INCOMPLETE")
