import subprocess
r = subprocess.run(['ssh','-o','ConnectTimeout=5','-o','BatchMode=yes','zantao@NASGZT.local',
  'date -r $(stat -c %Y "/share/CACHEDEV1_DATA/DS-M4/macbook备份/models") "+models mtime %F %T"; ls "/share/CACHEDEV1_DATA/DS-M4/macbook备份/" | head'],
  capture_output=True, text=True, timeout=20)
print(r.stdout); print('ERR', r.stderr[:200])
