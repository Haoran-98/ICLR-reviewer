#!/usr/bin/env bash
set -euo pipefail

S4_SERVER="${ICLR_LLAMA_SERVER:?Set ICLR_LLAMA_SERVER to the llama-server executable}"
S4_TOOLCHAIN="${ICLR_LLAMA_TOOLCHAIN:?Set ICLR_LLAMA_TOOLCHAIN to the toolchain environment file}"
S4_WEIGHTS="${ICLR_QWEN_WEIGHTS:?Set ICLR_QWEN_WEIGHTS to the GGUF file}"
S4_SLOTS="${S4_SLOTS:-4}"
S4_KV_ARGS=(--no-kv-unified)
if (( S4_SLOTS > 1 )); then
  S4_KV_ARGS=(--kv-unified --kv-unified-per-slot 65536)
fi

export LD_LIBRARY_PATH="$S4_TOOLCHAIN/lib:$S4_TOOLCHAIN/targets/x86_64-linux/lib:${LD_LIBRARY_PATH:-}"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

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
