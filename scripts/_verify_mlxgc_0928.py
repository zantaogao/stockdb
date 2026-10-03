import json, os, shutil, subprocess, urllib.request

print("=== 磁盘 ===")
print(subprocess.run(["df", "-h", "/System/Volumes/Data"], capture_output=True, text=True).stdout.strip().splitlines()[-1])

print("=== kv-cache ===")
print(subprocess.run(["du", "-sh", os.path.expanduser("~/.mlx-serve/kv-cache")],
                     capture_output=True, text=True).stdout.strip())

print("=== 服务 ===")
r = subprocess.run(["pgrep", "-f", "mlx-serve-26.9.3"], capture_output=True, text=True).stdout.split()
print("pid:", r)
print(subprocess.run(["ps", "-o", "etime=,lstart=", "-p", r[0]], capture_output=True, text=True).stdout.strip())
try:
    with urllib.request.urlopen("http://127.0.0.1:11234/v1/models", timeout=10) as fh:
        d = json.load(fh)["data"][0]
    print("model:", d["id"], "| state:", d["state"], "| ctx:", d["context_length"])
except Exception as e:
    print("模型端点异常:", e)

print("=== GC cron ===")
jobs = json.load(open(os.path.expanduser("~/.hermes/cron/jobs.json")))["jobs"]
j = [x for x in jobs if (x.get("id") or x.get("job_id")) == "70573919e1aa"][0]
print(j["name"], "|", j["schedule"], "| enabled:", j["enabled"],
      "| next:", j.get("next_run_at"), "| last:", j.get("last_status"), j.get("last_run_at"))

print("=== episode 数 ===")
for hd in os.listdir(os.path.expanduser("~/.mlx-serve/kv-cache")):
    d = os.path.join(os.path.expanduser("~/.mlx-serve/kv-cache"), hd)
    if os.path.isdir(d):
        print(hd, len([x for x in os.listdir(d) if x.startswith("e")]), "episodes")
