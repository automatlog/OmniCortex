# 🧪 Tests Directory

Complete test suite for OmniCortex - All testing files organized in one place.

---

## 📁 Directory Structure

```
tests/
├── __init__.py                     # Python package marker
├── README.md                       # This file
│
├── agent_questions_data.py         # Agent test questions database
├── agent_test_data.json            # Sample test data (JSON)
├── create_agent_test_suite.py      # Test suite generator
├── generate_agent_tests.py         # Test file generator
│
├── check_vllm_status.py            # vLLM status checker
├── quick_test_vllm.py              # Quick vLLM test
├── test_vllm.py                    # Full vLLM test suite
│
├── test_agents.py                  # Agent CRUD tests
├── test_api.py                     # FastAPI endpoint tests
├── test_webhook.py                 # Webhook tests
├── test_webhook_sender.py          # Webhook sender tests
│
├── evaluate_rag.py                 # RAG quality evaluation (Ragas)
├── locustfile.py                   # Load testing (Locust)
├── stress_test_heavy.py            # Heavy stress test
│
└── test_docs/                      # 56 PDF test documents
    ├── AI_Agent_Configurator.pdf
    ├── Automotive_and_Mobility.pdf
    └── ... (54 more PDFs)
```

---

## 🚀 Quick Start

### Run All Tests
```bash
# Using pytest
pytest tests/

# Or run specific test files
python tests/test_api.py
python tests/test_agents.py
python tests/test_vllm.py
```

### Check vLLM Status
```bash
python tests/check_vllm_status.py
```

### Generate Test Suite
```bash
python tests/create_agent_test_suite.py
```

### Load Testing
```bash
# Using Locust
locust -f tests/locustfile.py

# Heavy stress test
python tests/stress_test_heavy.py
```

### RAG Evaluation
```bash
python tests/evaluate_rag.py
```

---

## 📊 Test Categories

### 1. Unit Tests

**`test_api.py`** - FastAPI endpoint tests
```bash
python tests/test_api.py
```

**`test_agents.py`** - Agent CRUD operations
```bash
python tests/test_agents.py
```

---

### 2. Integration Tests

**`test_vllm.py`** - Full vLLM integration test
```bash
python tests/test_vllm.py
```

**`quick_test_vllm.py`** - Quick vLLM check
```bash
python tests/quick_test_vllm.py
```

**`test_webhook.py`** - Webhook functionality
```bash
python tests/test_webhook.py
```

---

### 3. Performance Tests

**`locustfile.py`** - Load testing with Locust
```bash
# Web UI
locust -f tests/locustfile.py

# Headless
locust -f tests/locustfile.py --headless -u 100 -r 10 -t 60s
```

**`stress_test_heavy.py`** - Heavy concurrent users
```bash
python tests/stress_test_heavy.py
```

---

### 4. Quality Tests

**`evaluate_rag.py`** - RAG quality metrics (Ragas)
```bash
python tests/evaluate_rag.py
```

Measures:
- Faithfulness
- Answer Relevance
- Context Precision
- Context Recall

---

### 5. Test Generation

**`create_agent_test_suite.py`** - Generate test suites
```bash
python tests/create_agent_test_suite.py
```

**`generate_agent_tests.py`** - Generate test files
```bash
python tests/generate_agent_tests.py
```

**`agent_questions_data.py`** - Test questions database
- Contains predefined questions for all agent types
- Used by test generators

---

## 🎯 Test Data

### test_docs/ - Agent Profile PDFs

56 PDF files with agent profiles for testing:

**Categories**:
- AI & Tech (AI Agent Configurator, Coding Bootcamp, etc.)
- Business (CRM, Analytics, Sales, etc.)
- Healthcare (Clinic, Dental, Mental Health, etc.)
- Finance (Banking, Investment, Tax, etc.)
- Education (Career Counselor, Exam Coach, etc.)
- E-commerce (Pizza Store, Plant Nursery, etc.)
- Services (Hotel, Movie Theater, Delivery, etc.)

**Usage**:
```bash
# Create agents from test docs
python scripts/create_bulk_agents.py
```

---

## 🔧 Prerequisites

### Install Test Dependencies

```bash
# Activate environment
source .venv/bin/activate

# Install testing tools
pip install pytest pytest-asyncio httpx

# For load testing
pip install locust

# For RAG evaluation
pip install ragas datasets
```

---

## 📝 Writing New Tests

### Example: API Test

```python
# tests/test_my_feature.py
import pytest
from fastapi.testclient import TestClient
from api import app

client = TestClient(app)

def test_my_endpoint():
    response = client.get("/my-endpoint")
    assert response.status_code == 200
    assert "expected_key" in response.json()
```

### Example: Agent Test

```python
# tests/test_my_agent.py
from core import create_agent, get_agent

def test_create_agent():
    agent_id = create_agent("Test Agent", "Test description")
    agent = get_agent(agent_id)
    assert agent["name"] == "Test Agent"
```

---

## 🐛 Debugging Tests

### Run with Verbose Output
```bash
pytest tests/ -v
```

### Run Specific Test
```bash
pytest tests/test_api.py::test_specific_function -v
```

### Run with Print Statements
```bash
pytest tests/ -s
```

### Run with Coverage
```bash
pytest tests/ --cov=core --cov-report=html
```

---

## 📊 Test Coverage

### Check Coverage
```bash
# Install coverage
pip install pytest-cov

# Run with coverage
pytest tests/ --cov=core --cov=api

# Generate HTML report
pytest tests/ --cov=core --cov=api --cov-report=html
open htmlcov/index.html
```

---

## 🚦 CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest tests/
```

---

## 📚 Documentation

- **Test Organization**: `CLEANUP_SUMMARY.md`
- **Agent Testing**: `AGENT_TESTING_GUIDE.md`
- **Integration Check**: `NEXTJS_BACKEND_INTEGRATION_CHECK.md`
- **Full Stack Guide**: `START_FULL_STACK.md`

---

## ✅ Test Checklist

Before committing:

- [ ] All tests pass: `pytest tests/`
- [ ] vLLM is working: `python tests/quick_test_vllm.py`
- [ ] API is working: `python tests/test_api.py`
- [ ] Agents work: `python tests/test_agents.py`
- [ ] No broken imports
- [ ] Code coverage > 80%

---

## 🎉 Summary

- **14 test files** covering all aspects
- **56 test documents** for agent testing
- **Multiple test types**: unit, integration, performance, quality
- **Easy to run**: Simple commands for all tests
- **Well organized**: Clear structure and documentation

**Happy Testing! 🧪**
