import json, os, sys, time
SD = os.path.expanduser("~/.hermes/stockdb")
sys.path.insert(0, SD)
os.chdir(SD)
from core.prices import fetch_prices_batch, _fetch_sina  # noqa

j = json.load(open(os.path.join(SD, "sim_accounts", "cmmr.json")))
pos_codes = [p["code"] for p in j.get("positions", [])]
print("cmmr positions:", len(pos_codes), pos_codes)

# targets today (signals) — approximate with positions + a few known target codes
test = pos_codes
t0 = time.time()
res = fetch_prices_batch(test)
print(f"fetch_prices_batch -> {len(res)}/{len(test)} prices in {time.time()-t0:.2f}s")
missing = [c for c in test if c not in res]
print("missing:", missing)

# raw single batch (bypass cache)
t0 = time.time()
raw = _fetch_sina(test)
print(f"_fetch_sina raw -> {len(raw)}/{len(test)} in {time.time()-t0:.2f}s")

# also test index codes used for market_ret
idx = _fetch_sina(["000852", "000001"])
print("index fetch:", {k: v["price"] for k, v in idx.items()})
