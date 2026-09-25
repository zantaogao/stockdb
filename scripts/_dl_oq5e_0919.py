import os, time
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from huggingface_hub import snapshot_download
path = snapshot_download(
    "mlx-community/Qwen3.8-Flash-Next-Uncensored-oQ5e-mtp",
    local_dir=os.path.expanduser("~/models/Qwen3.8-Flash-Next-Uncensored-oQ5e-mtp"),
    max_workers=4,
)
print("DONE", path)
