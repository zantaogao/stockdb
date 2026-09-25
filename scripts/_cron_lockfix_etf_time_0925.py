import json, shutil, sys
JP="/Users/zantao/.hermes/cron/jobs.json"
j=json.load(open(JP))
hit=0
for job in j.get("jobs",[]):
    if job.get("id")=="1eb1d98a7074":
        cfg=job.get("schedule_config") or {}
        print("before:", job.get("schedule"), cfg)
        job["schedule"]={"kind":"cron","expr":"50 17 * * 1-5"}
        if cfg.get("minute") is not None: cfg["minute"]=17*60+50
        job["schedule_config"]=cfg
        job["next_run_at"]=None
        hit+=1
assert hit==1, hit
bak=JP+".bak.lockfix"
shutil.copy(JP,bak)
tmp=JP+".lockfix.tmp"
json.dump(j,open(tmp,"w"),ensure_ascii=False,indent=2)
json.load(open(tmp))  # 验证可解析再替换
import os; os.replace(tmp,JP)
print("ETFTIME_DONE")
