"""扫 ~/.hermes/scripts/*.sh: 哪些脚本裸用 python3(未钉 /usr/bin/python3 或 export PATH)"""
import glob, os, re
for f in sorted(glob.glob(os.path.expanduser("~/.hermes/scripts/*.sh"))):
    if ".bak" in f: continue
    txt = open(f, errors="replace").read()
    has_export = re.search(r"^\s*export PATH", txt, re.M)
    if not has_export:
        lines = [i+1 for i, l in enumerate(txt.splitlines())
                 if re.search(r"(?<!/)\bpython3(\s+-B|\s+-c|\s*$)", l) and "/usr/bin/python3" not in l
                 and not l.strip().startswith("#")]
        if lines:
            print(os.path.basename(f), "-> 裸python3 行:", lines[:8])
