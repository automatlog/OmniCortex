# LLM Model Guide

Comparison of text-to-text and voice-to-voice models for OmniCortex.

---

## Text-to-Text Models

### Recommended for Production

| Model | Parameters | VRAM | Speed | Quality | Cost |
|-------|------------|------|-------|---------|------|
| **Llama-3.1-8B-Instruct** ⭐ | 8B | 16GB | Fast | Good | Free |
| Llama-3.1-70B-Instruct | 70B | 45GB | Slower | Excellent | Free |

### Model Selection Guide

| Use Case | Recommended Model |
|----------|-------------------|
| **General chatbot** | Llama-3.1-8B-Instruct |
| **Complex reasoning** | Llama-3.1-70B-Instruct |

---

## Voice-to-Voice Models

### LiquidAI LFM2.5-Audio (Recommended) ⭐

End-to-end audio model for real-time voice chat.

| Feature | Spec |
|---------|------|
| Type | Audio-to-Audio |
| Latency | <500ms |
| Languages | 12+ |
| Concurrent | 8-12 agents/GPU |
| License | Open-source |

```python
from core.voice.liquid_voice import LiquidVoiceEngine

engine = LiquidVoiceEngine()
response_audio = engine.process_audio(input_audio, agent_id)
```

### Voice Model Comparison

| Model | Type | Latency | Quality | Multi-Agent |
|-------|------|---------|---------|-------------|
| **LiquidAI LFM2.5** ⭐ | Audio→Audio | <500ms | Good | ✅ 8-12 |
| Whisper + LLM + TTS | Pipeline | 2-3s | Good | ❌ Sequential |
| OpenAI Realtime | Cloud API | <1s | Excellent | ✅ Unlimited |
| Moshi (Kyutai) | Audio→Audio | <200ms | Good | ⚠️ Limited |

### Why LiquidAI?

1. **End-to-End**: No separate ASR/TTS (faster)
2. **Multi-Agent**: 8-12 concurrent voice agents
3. **vLLM Compatible**: Same GPU pool
4. **Open Source**: No API costs
5. **Low Latency**: Real-time conversation

---

## Embedding Models

For RAG vector search:

| Model | Dimensions | Speed | Quality |
|-------|------------|-------|---------|
| **all-MiniLM-L6-v2** ⭐ | 384 | Fast | Good |
| bge-small-en-v1.5 | 384 | Fast | Better |
| bge-base-en-v1.5 | 768 | Medium | Better |
| e5-large-v2 | 1024 | Slower | Best |
| text-embedding-3-small | 1536 | API | Best |

**Current**: `all-MiniLM-L6-v2` (balance of speed & quality)

---

## Hardware Requirements

### For RTX 6000 Ada (48GB VRAM)

| Configuration | Models | Capacity |
|---------------|--------|----------|
| **Optimal** | Llama-3.1-8B + Embeddings | 80+ agents |
| High Quality | Llama-3.1-70B | 20-30 agents |
| With Voice | Llama-3.1-8B + LiquidAI | 50 agents + 8 voice |

### GPU Memory Budget

```
48GB Total VRAM:
├── vLLM (Llama-3.1-8B): ~16GB
├── Embeddings: ~2GB
├── LiquidAI Voice: ~8GB
└── Available: ~22GB buffer
```

---

## Model Performance Benchmarks

*Tested on 2x NVIDIA A10*

### Throughput (tokens/sec)

| Model | Batch 1 | Batch 32 | Batch 128 |
|-------|---------|----------|-----------|
| Llama-3.1-8B | 120 | 2,400 | 5,200 |
| Llama-3.1-70B | 25 | 600 | 1,200 |

### Latency (Time to First Token)

| Model | P50 | P95 | P99 |
|-------|-----|-----|-----|
| Llama-3.1-8B | 45ms | 120ms | 200ms |
| Llama-3.1-70B | 150ms | 400ms | 600ms |

---

## Switching Models

### Change vLLM Model

```bash
# Stop current
docker stop vllm && docker rm vllm

# Start with new model
docker run -d --gpus all --name vllm \
  -p 8080:8000 \
  vllm/vllm-openai:latest \
  --model NEW_MODEL_NAME
```

### Change in .env

```env
VLLM_MODEL=meta-llama/Meta-Llama-3.1-70B-Instruct
```

---

## Cost Analysis

### Self-Hosted (2x A10)

| Model | Cost/month |
|-------|------------|
| Any open model | $0 (just electricity) |

### Cloud APIs (100K messages/month)

| Provider | Est. Tokens | Cost/month |
|----------|-------------|------------|
| Groq | 50M tokens | ~$30 |
| Google | 50M tokens | ~$4 |
| OpenAI | 50M tokens | ~$8 |

**Recommendation**: Self-host Llama-3.1-8B for $0 cost.
