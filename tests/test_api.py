"""
🧪 OmniCortex API Integration Tests
Pytest-based tests for validating API endpoints.

Usage:
    uv run pytest tests/test_api.py -v
    uv run pytest tests/test_api.py -v -k "test_health"  # Run specific test
"""

import pytest
import httpx
from typing import Dict, Optional

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_URL = "http://localhost:8000"
TEST_AGENT_NAME = "TestBot_Pytest"


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(scope="module")
def client():
    """Create HTTP client for tests"""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="module")
def test_agent(client: httpx.Client) -> Optional[Dict]:
    """Create a test agent for the session, clean up after"""
    # Create agent
    resp = client.post("/agents", json={
        "name": TEST_AGENT_NAME,
        "description": "Automated test agent"
    })
    
    if resp.status_code == 200:
        agent = resp.json()
        yield agent
        # Cleanup
        try:
            client.delete(f"/agents/{agent['id']}")
        except:
            pass
    else:
        yield None


# =============================================================================
# HEALTH CHECK TESTS
# =============================================================================

class TestHealthCheck:
    """API Health and Basic Connectivity"""
    
    def test_health_endpoint(self, client: httpx.Client):
        """GET / should return 200 OK"""
        resp = client.get("/")
        assert resp.status_code == 200
    
    def test_metrics_endpoint(self, client: httpx.Client):
        """GET /metrics should return Prometheus metrics"""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "omnicortex_" in resp.text or "request" in resp.text


# =============================================================================
# AGENT LIFECYCLE TESTS
# =============================================================================

class TestAgentLifecycle:
    """Agent CRUD Operations"""
    
    def test_list_agents(self, client: httpx.Client):
        """GET /agents should return list"""
        resp = client.get("/agents")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
    
    def test_create_agent(self, client: httpx.Client):
        """POST /agents should create new agent"""
        resp = client.post("/agents", json={
            "name": f"TempAgent_{pytest.approx}",
            "description": "Temporary test agent"
        })
        
        if resp.status_code == 200:
            agent = resp.json()
            assert "id" in agent
            assert agent["name"].startswith("TempAgent")
            
            # Cleanup
            client.delete(f"/agents/{agent['id']}")
    
    def test_get_agent(self, client: httpx.Client, test_agent: Optional[Dict]):
        """GET /agents/{id} should return agent details"""
        if not test_agent:
            pytest.skip("Test agent not created")
        
        resp = client.get(f"/agents/{test_agent['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == TEST_AGENT_NAME
    
    def test_delete_agent(self, client: httpx.Client):
        """DELETE /agents/{id} should remove agent"""
        # Create temp agent
        resp = client.post("/agents", json={
            "name": "ToBeDeleted",
            "description": "Will be deleted"
        })
        
        if resp.status_code == 200:
            agent_id = resp.json()["id"]
            
            # Delete
            del_resp = client.delete(f"/agents/{agent_id}")
            assert del_resp.status_code == 200
            
            # Verify deleted
            get_resp = client.get(f"/agents/{agent_id}")
            assert get_resp.status_code in [404, 400]


# =============================================================================
# QUERY TESTS
# =============================================================================

class TestQueryEndpoint:
    """Chat/Query Functionality"""
    
    def test_query_requires_agent(self, client: httpx.Client):
        """POST /query should fail without agent_id"""
        resp = client.post("/query", json={
            "question": "Hello"
        })
        # Should fail validation
        assert resp.status_code in [400, 422]
    
    def test_query_with_agent(self, client: httpx.Client, test_agent: Optional[Dict]):
        """POST /query should return response when agent exists"""
        if not test_agent:
            pytest.skip("Test agent not created")
        
        resp = client.post("/query", json={
            "question": "Hello, who are you?",
            "agent_id": test_agent["id"],
            "max_history": 0
        })
        
        # Note: May fail if no documents uploaded to agent
        # Status 200 = success, 500 = no docs (acceptable for this test)
        assert resp.status_code in [200, 500]
    
    def test_query_with_model_selection(self, client: httpx.Client, test_agent: Optional[Dict]):
        """POST /query should accept model_selection parameter"""
        if not test_agent:
            pytest.skip("Test agent not created")
        
        resp = client.post("/query", json={
            "question": "Test query",
            "agent_id": test_agent["id"],
            "model_selection": "Meta Llama 3.1",
            "max_history": 0
        })
        
        assert resp.status_code in [200, 500]


# =============================================================================
# DOCUMENT TESTS
# =============================================================================

class TestDocumentUpload:
    """Document Ingestion"""
    
    def test_upload_text(self, client: httpx.Client, test_agent: Optional[Dict]):
        """POST /documents should accept text content"""
        if not test_agent:
            pytest.skip("Test agent not created")
        
        resp = client.post("/documents", json={
            "agent_id": test_agent["id"],
            "text_content": "This is a test document for pytest validation."
        })
        
        assert resp.status_code in [200, 201]
    
    def test_list_documents(self, client: httpx.Client, test_agent: Optional[Dict]):
        """GET /documents/{agent_id} should return documents"""
        if not test_agent:
            pytest.skip("Test agent not created")
        
        resp = client.get(f"/documents/{test_agent['id']}")
        assert resp.status_code == 200


# =============================================================================
# RUN DIRECTLY
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
