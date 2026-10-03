import sqlite3, os
home = os.path.expanduser('~/.hermes')
targets = {'ic_daily','ic_window','factor_ic_roll','cmmr_ic_daily','fusion_ic_daily','etf_ic','factor_group_ic_daily'}
for root, dirs, files in os.walk(home, topdown=True):
    dirs[:] = [d for d in dirs if d not in ('sessions','cache','logs','backups','db_backups','venv','.git','node_modules','profiles','audio_cache','images')]
    for f in files:
        if f.endswith('.db'):
            p = os.path.join(root, f)
            try:
                c = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
                names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                hit = names & targets
                if hit:
                    print(p, sorted(hit))
                c.close()
            except Exception:
                pass
