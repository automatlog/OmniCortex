# 🧠 OmniCortex - Multi-Agent RAG Platform

**Version 2.0** | Modern AI chatbot platform with multi-agent support, RAG pipeline, and omnichannel deployment.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🚀 Features

- **🤖 Multi-Agent System** - Create unlimited isolated AI agents with custom knowledge bases
- **📚 RAG Pipeline** - Upload PDFs, DOCX, TXT, CSV for agent-specific knowledge
- **💻 Local LLM** - Run Llama 3.1 via vLLM (zero API costs)
- **🎙️ Voice Chat** - Real-time audio with LiquidAI or ElevenLabs
- **💬 WhatsApp Integration** - Deploy agents via WhatsApp Business API
- **📊 Analytics** - ClickHouse integration for usage tracking
- **🔄 Persistent Memory** - Conversation history per user/agent
- **⚡ High Performance** - Handles 50+ concurrent agents

---

## 📋 Quick Start

### Cloud Deployment (RunPod - Recommended) ☁️

**5-minute setup with cost-effective GPU instances**

1. **Create RunPod Account**: [RunPod.io](https://runpod.io)
2. **Deploy Pod**: Select PyTorch template + RTX 4090 GPU
3. **Connect**: Use Web Terminal or SSH
4. **Run Script**:
```bash
git clone <your-repo-url> /workspace/OmniCortex
cd /workspace/OmniCortex
chmod +x scripts/deploy_runpod.sh
sudo ./scripts/deploy_runpod.sh
```
5. **Access**: Get URLs from RunPod dashboard (ports 8000, 8501)

**Cost**: ~$0.34/hr (~$245/month for 24/7)

See [RUNPOD.md](docs/RUNPOD.md) for detailed guide.

---

### Local Development 💻

### Prerequisites

- **Python 3.12+**
- **PostgreSQL 16+** with pgvector extension
- **NVIDIA GPU** (24GB+ VRAM recommended - RTX 4090, RTX 3090, A40, or A100)
- **uv** package manager
- **RunPod account** (for cloud deployment) or local GPU setup

### 1. Install uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone & Setup

```bash
git clone <your-repo-url>
cd OmniCortex

# Create virtual environment
uv venv --python 3.12

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/macOS)
source .venv/bin/activate

# Install dependencies
uv pip install -e .
```

### 3. Configure Environment

```bash
# Copy example config
copy .env.example .env

# Edit .env with your settings
notepad .env
```

**Required settings:**
```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/omnicortex
VLLM_BASE_URL=http://localhost:8080/v1
VLLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
```

### 4. Setup Database

```bash
# Create database
psql -U postgres -c "CREATE DATABASE omnicortex;"

# Enable pgvector extension
psql -U postgres -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 5. Start Services

**Terminal 1 - Start vLLM Server:**
```bash
docker run --gpus all -p 8080:8000 ^
  -v %USERPROFILE%\.cache\huggingface:/root/.cache/huggingface ^
  vllm/vllm-openai:latest ^
  --model meta-llama/Meta-Llama-3.1-8B-Instruct ^
  --max-model-len 8192
```

**Terminal 2 - Start API Server:**
```bash
uv run python api.py
```

**Terminal 3 - Start Next.js Admin Panel:**
```bash
cd admin
npm run dev
```

### 6. Access Application

- **Admin Panel**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Metrics**: http://localhost:8000/metrics

---

## 📖 Documentation

Comprehensive guides available in the `docs/` folder:

| Document | Description |
|----------|-------------|
| [PROJECT.md](docs/PROJECT.md) | Architecture & design decisions |
| [SETUP.md](docs/SETUP.md) | Detailed installation guide |
| [DEPLOYMENT_COMPARISON.md](docs/DEPLOYMENT_COMPARISON.md) | Compare deployment options |
| [RUNPOD.md](docs/RUNPOD.md) | RunPod GPU deployment (Recommended) |
| [DEPLOY.md](docs/DEPLOY.md) | General production deployment |
| [POSTGRESQL.md](docs/POSTGRESQL.md) | Database setup & configuration |
| [vLLM.md](docs/vLLM.md) | LLM server setup & tuning |
| [LLM.md](docs/LLM.md) | Model selection guide |
| [CLICKHOUSE.md](docs/CLICKHOUSE.md) | Analytics setup (optional) |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLIENT LAYER                           │
│   [Next.js Admin]  [WhatsApp API]  [Voice/LiquidAI]         │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   APPLICATION LAYER                         │
│   [FastAPI :8000]  ←→  [vLLM Server :8080]                  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     CORE SERVICES                           │
│   [Agent Manager]  [Chat Service]  [RAG Pipeline]           │
│   [Document Processor]  [Vector Store]                      │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                       DATA LAYER                            │
│   [PostgreSQL + pgvector]  [ClickHouse]  [File Storage]     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy |
| **UI** | Next.js + TypeScript + Tailwind CSS |
| **LLM** | vLLM + Llama 3.1-8B-Instruct |
| **Embeddings** | HuggingFace all-MiniLM-L6-v2 |
| **Database** | PostgreSQL 16 + pgvector |
| **Analytics** | ClickHouse (optional) |
| **Voice** | LiquidAI / ElevenLabs |
| **Orchestration** | LangChain, LangGraph, CrewAI |
| **Package Manager** | uv (Astral) |

---

## 📊 Performance

Tested on RTX 4090 (24GB VRAM):

| Metric | Target | Achieved |
|--------|--------|----------|
| Concurrent Agents | 50+ | ✅ 80 |
| Response Latency | <3s | ✅ 1-2s |
| Throughput | 2000+ tok/s | ✅ 5200 tok/s |
| API Cost | $0 | ✅ Local LLM |
| Hosting Cost | - | ✅ $0.34/hr (RunPod) |

---

## 🔧 Configuration

### Port Configuration

| Service | Port | Description |
|---------|------|-------------|
| vLLM Server | 8080 | LLM inference engine |
| FastAPI | 8000 | REST API backend |
| Next.js Admin | 3000 | Web Admin Panel |
| PostgreSQL | 5432 | Database |
| ClickHouse | 8123 | Analytics (optional) |

### Environment Variables

See `.env.example` for all available configuration options.

**Core Settings:**
- `DATABASE_URL` - PostgreSQL connection string
- `VLLM_BASE_URL` - vLLM server endpoint
- `VLLM_MODEL` - Model name/path
- `EMBEDDING_MODEL` - HuggingFace embedding model

**Optional:**
- `WHATSAPP_ACCESS_TOKEN` - Meta Business API token
- `WHATSAPP_PHONE_ID` - WhatsApp phone number ID
- `CLICKHOUSE_HOST` - Analytics database host

---

## 🎯 Use Cases

- **Customer Support** - Deploy AI agents with company knowledge
- **Internal Knowledge Base** - Query documents via chat
- **Multi-tenant SaaS** - Isolated agents per customer
- **Voice Assistants** - Real-time audio conversations
- **WhatsApp Bots** - Automated messaging with RAG

---

## 🐛 Troubleshooting

### "Connection refused" (Database)
```bash
# Windows: Start PostgreSQL service
services.msc → postgresql-x64-16 → Start

# Linux
sudo systemctl start postgresql
```

### "CUDA out of memory"
Reduce vLLM batch size:
```bash
--max-num-seqs 64 --gpu-memory-utilization 0.85
```

### "No module named 'core'"
```bash
uv pip install -e .
```

### vLLM not responding
Check if server is running:
```bash
curl http://localhost:8080/health
```

---

## 📝 Project Structure

```
OmniCortex/
├── core/                   # Core modules
│   ├── agent_manager.py    # Agent CRUD
│   ├── chat_service.py     # RAG orchestration
│   ├── llm.py              # LLM integration
│   ├── database.py         # SQLAlchemy models
│   ├── processing/         # Document processing
│   ├── rag/                # Vector store & embeddings
│   └── voice/              # Voice processing
├── config/                 # YAML configurations
├── docs/                   # Documentation
├── scripts/                # Deployment scripts
├── tests/                  # Test suite
├── api.py                  # FastAPI backend
├── admin/                 # Next.js Admin Panel
└── pyproject.toml          # Dependencies
```

---

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## 📄 License

MIT License - see LICENSE file for details

---

## 🙏 Acknowledgments

- **Meta** - Llama 3.1 models
- **vLLM Team** - High-performance inference
- **LangChain** - LLM orchestration framework
- **PostgreSQL** - Reliable database
- **Next.js** - Modern React framework for admin panel

---

## 📞 Support

- **Documentation**: See `docs/` folder
- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions

---

**Built with ❤️ for the AI community**
