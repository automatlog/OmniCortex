# vLLM & SGLang Guide

High-performance LLM inference servers for production deployment.

---

## vLLM Overview

**vLLM** is an open-source LLM serving engine optimized for:
- **PagedAttention**: Efficient memory management
- **Continuous Batching**: High throughput
- **OpenAI-Compatible API**: Drop-in replacement

### Key Specs

| Feature | Value |
|---------|-------|
| Throughput | 5000+ tokens/sec |
| Latency | <100ms TTFT |
| Memory | Optimized via PagedAttention |
| API | OpenAI-compatible |

---

## Installation

### Docker (Recommended)

```bash
docker run --gpus all -p 8080:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --tensor-parallel-size 2 \
  --max-num-seqs 128 \
  --gpu-memory-utilization 0.90
```

### pip Install (Linux)

```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --port 8080
```

---

## Configuration Options

| Flag | Description | Default |
|------|-------------|---------|
| `--model` | Model path/name | Required |
| `--tensor-parallel-size` | GPUs to use | 1 |
| `--max-num-seqs` | Max concurrent requests | 256 |
| `--gpu-memory-utilization` | VRAM usage (0-1) | 0.90 |
| `--max-model-len` | Context length | Model default |
| `--port` | API port | 8000 |

---

## OmniCortex Integration

### Environment Variables
```env
USE_VLLM=true
VLLM_BASE_URL=http://localhost:8080/v1
VLLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
```

### Python Client
```python
from core.inference import VLLMClient, get_vllm_client

client = get_vllm_client()
response = client.chat("Hello, who are you?")
print(response)
```

---

## SGLang Alternative

**SGLang** is an alternative serving engine with different strengths.

### vLLM vs SGLang Comparison

| Metric | vLLM | SGLang |
|--------|------|--------|
| **Throughput (high concurrency)** | ✅ 10-15% better | Good |
| **TTFT (low concurrency)** | 2141ms | ✅ 583ms (3.7x faster) |
| **Memory Usage** | 75GB/GPU | ✅ 40GB/GPU (47% less) |
| **Structured Output** | Good | ✅ Better (RadixAttention) |
| **Long Context (8K+)** | ✅ 2x better | Good |
| **Multi-GPU Scaling** | ✅ Mature | Improving |
| **Ecosystem** | ✅ Larger community | Growing |

### When to Use Which

| Use Case | Recommendation |
|----------|----------------|
| High concurrency (50+ users) | **vLLM** |
| Low concurrency (<10 users) | **SGLang** |
| Memory-constrained | **SGLang** |
| Structured JSON output | **SGLang** |
| Long documents (8K+ tokens) | **vLLM** |
| Production stability | **vLLM** |

---

## SGLang Installation

```bash
pip install sglang[all]

python -m sglang.launch_server \
  --model-path meta-llama/Meta-Llama-3.1-8B-Instruct \
  --port 8080
```
---

## Performance Tuning

### High Throughput
```bash
--max-num-seqs 256 \
--gpu-memory-utilization 0.95 \
--disable-log-requests
```

### Low Latency
```bash
--max-num-seqs 32 \
--use-v2-block-manager
```

### Memory Constrained
```bash
--max-model-len 4096 \
--gpu-memory-utilization 0.85 \
--swap-space 10
```

---

## Monitoring

```bash
# GPU usage
nvidia-smi -l 1

# vLLM metrics
curl http://localhost:8080/metrics

# Health check
curl http://localhost:8080/health
```

---

## Troubleshooting

### "CUDA out of memory"
```bash
# Reduce memory usage
--gpu-memory-utilization 0.80 \
--max-num-seqs 64
```

### "Model not found"
```bash
# Login to HuggingFace for gated models
huggingface-cli login
```

### Slow inference
```bash
# Use tensor parallelism across GPUs
--tensor-parallel-size 2
```
