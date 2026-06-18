#!/usr/bin/env python3
"""Download the ONNX embedding model for the F1 retrieval layer."""
import os
from pathlib import Path

MODEL_DIR = Path.home() / ".hermes" / "models" / "miniLM-onnx"
ONNX_DIR = MODEL_DIR / "onnx"
MODEL_PATH = ONNX_DIR / "model.onnx"

if MODEL_PATH.exists():
    size = os.path.getsize(MODEL_PATH)
    print(f"✅ Model already exists ({size / 1e6:.0f}MB)")
    exit(0)

os.makedirs(ONNX_DIR, exist_ok=True)

print("Downloading all-MiniLM-L6-v2 ONNX model (~86MB)...")

from huggingface_hub import hf_hub_download

for filename in ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]:
    path = hf_hub_download(
        repo_id="sentence-transformers/all-MiniLM-L6-v2",
        filename=filename,
        local_dir=str(MODEL_DIR),
        local_dir_use_symlinks=False,
    )
    print(f"  ✅ {filename}")

path = hf_hub_download(
    repo_id="sentence-transformers/all-MiniLM-L6-v2",
    filename="onnx/model.onnx",
    local_dir=str(MODEL_DIR),
    local_dir_use_symlinks=False,
)

size = os.path.getsize(path)
print(f"  ✅ model.onnx ({size / 1e6:.0f}MB)")
print(f"\nModel ready at {MODEL_DIR}")
