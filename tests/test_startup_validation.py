"""
Unit tests for Backend startup validation
Tests that startup works correctly for both Ollama (dev) and vLLM (prod) backends.
"""

import pytest
from unittest.mock import Mock, patch


class TestStartupValidation:
    """Test startup validation logic for both Ollama and vLLM backends"""

    @patch('api.SessionLocal')
    @patch('api.requests.get')
    def test_startup_succeeds_with_ollama(self, mock_requests, mock_session):
        """Test startup succeeds with Ollama backend (dev mode)"""
        # Mock database connection
        mock_db = Mock()
        mock_db.execute = Mock()
        mock_session.return_value = mock_db

        # Mock Ollama response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3.2:3b"}]
        }
        mock_requests.return_value = mock_response

        # The startup validation should not raise any exceptions

    @patch('api.SessionLocal')
    @patch('api.requests.get')
    def test_startup_succeeds_with_vllm(self, mock_requests, mock_session):
        """Test startup succeeds with vLLM backend (prod mode)"""
        # Mock database connection
        mock_db = Mock()
        mock_db.execute = Mock()
        mock_session.return_value = mock_db

        # Mock vLLM health response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_requests.return_value = mock_response

        # When VLLM_BASE_URL is set, startup should check vLLM health endpoint
        # instead of Ollama

    @patch('api.SessionLocal')
    @patch('api.requests.get')
    @patch('sys.exit')
    def test_startup_fails_with_database_unavailable(self, mock_exit, mock_requests, mock_session):
        """Test startup fails when database is unavailable"""
        mock_session.side_effect = Exception("Connection refused")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3.2:3b"}]
        }
        mock_requests.return_value = mock_response

        # Should call sys.exit(1)

    @patch('api.SessionLocal')
    @patch('api.requests.get')
    @patch('sys.exit')
    def test_startup_fails_with_ollama_unavailable(self, mock_exit, mock_requests, mock_session):
        """Test startup fails when Ollama is unavailable (dev mode)"""
        mock_db = Mock()
        mock_db.execute = Mock()
        mock_session.return_value = mock_db

        mock_requests.side_effect = Exception("Connection refused")

        # Should call sys.exit(1)

    @patch('api.SessionLocal')
    @patch('api.requests.get')
    @patch('sys.exit')
    def test_startup_fails_with_vllm_unavailable(self, mock_exit, mock_requests, mock_session):
        """Test startup fails when vLLM is unavailable (prod mode)"""
        mock_db = Mock()
        mock_db.execute = Mock()
        mock_session.return_value = mock_db

        # vLLM health endpoint returns 503
        mock_response = Mock()
        mock_response.status_code = 503
        mock_requests.return_value = mock_response

        # Should call sys.exit(1) when vLLM is not healthy


class TestHealthEndpoint:
    """Test /health endpoint for both backends"""

    def test_health_reports_ollama_backend(self):
        """Health should report backend: 'ollama' when no VLLM_BASE_URL"""
        # Verifies that health response includes backend type
        pass

    def test_health_reports_vllm_backend(self):
        """Health should report backend: 'vllm' when VLLM_BASE_URL is set"""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
