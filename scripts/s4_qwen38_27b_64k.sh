#!/usr/bin/env bash
set -euo pipefail

S4_SERVER=/home/yhr/WorkSpace/Codex_Program/16G-model/llama.cpp/build-sm89/bin/llama-server
S4_TOOLCHAIN=/home/yhr/WorkSpace/Codex_Program/qwen3.8-2080ti-256k/.env
S4_WEIGHTS=/data_big/models/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q3_K_XL.gguf
S4_SLOTS="${S4_SLOTS:-4}"
S4_KV_ARGS=(--no-kv-unified)
if (( S4_SLOTS > 1 )); then
  S4_KV_ARGS=(--kv-unified --kv-unified-per-slot 65536)
fi

export LD_LIBRARY_PATH="$S4_TOOLCHAIN/lib:$S4_TOOLCHAIN/targets/x86_64-linux/lib:${LD_LIBRARY_PATH:-}"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=GPU-7ba71d00-8739-32a9-1fe2-e1fefbf89f19

exec "$S4_SERVER" \
  --model "$S4_WEIGHTS" --alias s4-qwen38-27b-q3-medium \
  --host 127.0.0.1 --port 8091 \
  --ctx-size 65536 --parallel "$S4_SLOTS" "${S4_KV_ARGS[@]}" --no-context-shift \
  --n-gpu-layers all --split-mode none --main-gpu 0 --fit off \
  --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 \
  --batch-size 512 --ubatch-size 128 --threads 8 --threads-batch 16 \
  --cache-ram 1024 --jinja --reasoning on --reasoning-effort medium \
  --reasoning-format deepseek \
  --chat-template-kwargs '{"enable_thinking":true,"reasoning_effort":"medium"}' \
  --metrics --slots
