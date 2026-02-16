import uuid

import requests
from fastapi.testclient import TestClient

from api import app
from core.agent_manager import get_agent
from core.auth import create_new_api_key
from core.database import SessionLocal
from core.processing import scraper

# Disable expensive startup/shutdown handlers in tests.
app.router.on_startup.clear()
app.router.on_shutdown.clear()

client = TestClient(app)
_AUTH_HEADERS = {}


def _get_auth_headers():
    global _AUTH_HEADERS
    if _AUTH_HEADERS:
        return _AUTH_HEADERS
    db = SessionLocal()
    try:
        key = create_new_api_key("test_phase1", db)
    finally:
        db.close()
    _AUTH_HEADERS = {"X-API-Key": key}
    return _AUTH_HEADERS


def _new_name(prefix: str = "Phase1Agent") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_create_agent_with_extended_payload(monkeypatch):
    monkeypatch.setattr("api.process_documents", lambda *args, **kwargs: {"success": True})
    monkeypatch.setattr("api.process_urls", lambda *args, **kwargs: {"success": True})

    payload = {
        "name": _new_name(),
        "description": "Phase 1 full payload test",
        "system_prompt": "You are a business assistant.",
        "role_type": "business",
        "industry": "Retail Commerce Assistant",
        "urls": ["https://example.com"],
        "conversation_starters": ["Hello", "Can you help me?"],
        "image_urls": ["https://example.com/image.jpg"],
        "video_urls": ["https://example.com/video.mp4"],
        "documents_text": [
            {
                "filename": "catalog.txt",
                "text": "This is extracted full text from a product catalog."
            }
        ],
        "scraped_data": [
            {
                "url": "https://example.com/help",
                "text": "This is pre-scraped support content."
            }
        ]
    }

    response = client.post("/agents", json=payload, headers=_get_auth_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    agent_id = body["id"]

    try:
        assert body["name"] == payload["name"]
        assert body["role_type"] == "business"
        assert body["industry"] == "Retail Commerce Assistant"
        assert body["urls"] == payload["urls"]
        assert body["conversation_starters"] == payload["conversation_starters"]
        assert body["image_urls"] == payload["image_urls"]
        assert body["video_urls"] == payload["video_urls"]
        assert isinstance(body["scraped_data"], list)

        # Verify DB fetch path includes new fields.
        stored = get_agent(agent_id)
        assert stored is not None
        assert stored["role_type"] == "business"
        assert stored["industry"] == "Retail Commerce Assistant"
    finally:
        client.delete(f"/agents/{agent_id}", headers=_get_auth_headers())


def test_create_agent_rejects_business_without_industry():
    payload = {
        "name": _new_name(),
        "role_type": "business",
        "description": "Should fail because industry is missing"
    }
    response = client.post("/agents", json=payload, headers=_get_auth_headers())
    assert response.status_code == 400
    assert "industry is required" in response.json()["detail"]


def test_create_agent_enforces_url_limit():
    payload = {
        "name": _new_name(),
        "role_type": "knowledge",
        "urls": [f"https://example.com/page/{i}" for i in range(26)]
    }
    response = client.post("/agents", json=payload, headers=_get_auth_headers())
    assert response.status_code == 400
    assert "urls limit exceeded" in response.json()["detail"]


def test_update_agent_extended_fields(monkeypatch):
    monkeypatch.setattr("api.process_documents", lambda *args, **kwargs: {"success": True})
    create_payload = {"name": _new_name(), "description": "before update"}
    create_resp = client.post("/agents", json=create_payload, headers=_get_auth_headers())
    assert create_resp.status_code == 200, create_resp.text
    agent_id = create_resp.json()["id"]

    try:
        update_payload = {
            "description": "after update",
            "role_type": "knowledge",
            "conversation_starters": ["Start here"],
            "image_urls": ["https://example.com/new-image.png"],
            "video_urls": ["https://example.com/new-video.mp4"],
        }
        update_resp = client.put(f"/agents/{agent_id}", json=update_payload, headers=_get_auth_headers())
        assert update_resp.status_code == 200, update_resp.text
        body = update_resp.json()
        assert body["description"] == "after update"
        assert body["role_type"] == "knowledge"
        assert body["industry"] is None
        assert body["conversation_starters"] == ["Start here"]
        assert body["image_urls"] == ["https://example.com/new-image.png"]
        assert body["video_urls"] == ["https://example.com/new-video.mp4"]
    finally:
        client.delete(f"/agents/{agent_id}", headers=_get_auth_headers())


def test_scrape_url_extracts_text(monkeypatch):
    class FakeResponse:
        content = b"""
        <html>
          <head><title>Demo</title></head>
          <body>
            <h1>Example Domain</h1>
            <script>ignored()</script>
            <p>Useful content</p>
          </body>
        </html>
        """

        def raise_for_status(self):
            return None

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    text = scraper.scrape_url("https://example.com")
    assert "Example Domain" in text
    assert "Useful content" in text
    assert "ignored()" not in text


def test_scrape_url_handles_timeout(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise requests.exceptions.Timeout("timeout")

    monkeypatch.setattr(scraper.requests, "get", raise_timeout)
    text = scraper.scrape_url("https://example.com")
    assert text == ""
