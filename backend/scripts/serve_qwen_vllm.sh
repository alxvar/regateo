#!/usr/bin/env bash
# Serve a local Qwen model with vLLM on one GPU, as the `qwen-local` profile expects.
#
# Memory: a 27B model in bf16 needs ~54 GB of weights and does not fit a 32 GB RTX 5090.
# Use a quantised checkpoint: FP8 (~27 GB) leaves little room for KV cache, so parallel
# sessions and context length suffer; AWQ/GPTQ 4-bit (~15 GB) leaves ~14 GB for KV cache
# and suits many concurrent matches. vLLM reads the quantisation from the checkpoint.
#
#   QWEN_MODEL=<hf repo or local path> scripts/serve_qwen_vllm.sh
set -euo pipefail

: "${QWEN_MODEL:?set QWEN_MODEL to a quantised Qwen checkpoint (HF repo id or local path)}"
PORT="${PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"      # negotiations are short; lower = more parallel sessions
MAX_NUM_SEQS="${MAX_NUM_SEQS:-32}"           # keep configs/models/qwen-local.yaml max_concurrency <= this
REASONING_PARSER="${REASONING_PARSER:-qwen3}"

exec vllm serve "$QWEN_MODEL" \
  --served-model-name qwen-local \
  --port "$PORT" \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --gpu-memory-utilization 0.92 \
  --kv-cache-dtype fp8 \
  --enable-prefix-caching \
  --reasoning-parser "$REASONING_PARSER" \
  "$@"
