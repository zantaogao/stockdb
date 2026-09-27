import json, struct, collections, os
D = "/Users/zantao/models/Qwen3.8-Flash-Next-Uncensored-MLX-Serve-4bit/"
wm = json.load(open(D + "model.safetensors.index.json"))["weight_map"]

# 从第一个 shard 的 header 读 layer0/1 的 expert 权重 shape
sha...[truncated]