#!/usr/bin/env bash
# vLLM generation server, pinned to the second T4.
# GPU 0 is left free for the embedder + reranker in the RAG service.
set -euo pipefail

# Qwen2.5-14B-Instruct-AWQ: ~9GB of weights, leaving ~5GB for KV cache on a
# 16GB T4. Well-tested on Turing. Alternatives:
#   Qwen/Qwen3-14B-AWQ                 - newer, same footprint
#   Qwen/Qwen2.5-7B-Instruct-AWQ       - if you want more KV cache / longer ctx
MODEL="${MODEL:-Qwen/Qwen2.5-14B-Instruct-AWQ}"

export CUDA_VISIBLE_DEVICES=1

exec python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" \
  --quantization awq \
  --dtype half \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 8 \
  --no-enable-log-requests \
  --host 0.0.0.0 \
  --port 8001

# --dtype half is mandatory, not a preference. Turing (sm75) has no bfloat16
# support, and AWQ kernels are float16-only. Letting dtype default to "auto"
# reads bfloat16 from the model config and the server refuses to start.
#
# --max-model-len 8192 is a KV-cache budget decision. Turing also has no
# FlashAttention support, so vLLM falls back to the xformers backend and KV
# cache stays fp16 - there is no fp8 cache option to stretch this further.
# Raising context means fewer concurrent sequences.
