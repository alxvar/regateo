#!/usr/bin/env bash
# Serve a local Qwen model with vLLM on one GPU, as the `qwen-local` profile expects.
#
# Default: unsloth/Qwen3.8-27B-NVFP4 on a 32 GB RTX 5090. NVFP4 MLPs + FP8 attention is ~22.6 GB
# of weights; Blackwell runs FP4 natively. Only 16 of its 64 layers are full attention (~32 KB/token
# of fp8 KV cache); the 48 Gated DeltaNet layers hold a fixed ~75 MB state per sequence. That leaves
# room for ~16 concurrent negotiations. vLLM logs the real KV cache size and max concurrency at startup.
#
#   scripts/serve_qwen_vllm.sh                       # vLLM from ~/venvs/vllm, or $VLLM
#   QWEN_MODEL=<hf repo or path> scripts/serve_qwen_vllm.sh
set -euo pipefail

QWEN_MODEL="${QWEN_MODEL:-unsloth/Qwen3.8-27B-NVFP4}"
VLLM="${VLLM:-$(command -v vllm || echo "$HOME/venvs/vllm/bin/vllm")}"
PORT="${PORT:-8001}"                         # regateo serve (the dashboard) uses 8000
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"      # negotiations are short; lower = more parallel sessions
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"           # keep configs/models/qwen-local.yaml max_concurrency <= this
GPU_UTIL="${GPU_UTIL:-0.90}"                 # the desktop holds ~2 GB of the card
REASONING_PARSER="${REASONING_PARSER:-qwen3}"
export PATH="$(dirname "$VLLM"):$PATH"     # ninja, used by FlashInfer JIT builds
ATTN_BACKEND="${ATTN_BACKEND:-}"            # empty = vLLM's choice (FlashInfer); TRITON_ATTN needs no nvcc

# FlashInfer JIT-compiles some kernels (sampling, fp8-KV prefill on sm_120) and needs nvcc. With no
# system CUDA toolkit, use the one pip installs next to vLLM (nvidia/cu13). Precompiled kernels:
#   uv pip install flashinfer-jit-cache==<flashinfer version> --index-url https://flashinfer.ai/whl/cu130
if [[ -z "${CUDA_HOME:-}" ]] && ! command -v nvcc >/dev/null; then
  for d in "$(dirname "$VLLM")"/../lib/python3*/site-packages/nvidia/cu13; do
    [[ -x "$d/bin/nvcc" ]] && export CUDA_HOME="$(cd "$d" && pwd)" PATH="$d/bin:$PATH"
  done
  # FlashInfer links with -L$CUDA_HOME/lib64 -lcudart; the pip layout has lib/libcudart.so.13 only.
  if [[ -n "${CUDA_HOME:-}" ]]; then
    [[ -e "$CUDA_HOME/lib64" ]] || ln -s lib "$CUDA_HOME/lib64"
    [[ -e "$CUDA_HOME/lib/libcudart.so" ]] || ln -s libcudart.so.13 "$CUDA_HOME/lib/libcudart.so"
  fi
fi

exec "$VLLM" serve "$QWEN_MODEL" \
  --served-model-name qwen-local \
  --port "$PORT" \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --kv-cache-dtype fp8 \
  ${ATTN_BACKEND:+--attention-backend "$ATTN_BACKEND"} \
  --limit-mm-per-prompt '{"image":0,"video":0}' \
  --reasoning-parser "$REASONING_PARSER" \
  "$@"
