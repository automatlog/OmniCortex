import importlib
import sys


class _DummyResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _import_moshi_engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    sys.modules.pop("core.config", None)
    sys.modules.pop("core.voice.moshi_engine", None)
    return importlib.import_module("core.voice.moshi_engine")


def test_moshi_engine_checks_health_endpoint_first_for_ws_base_url(monkeypatch):
    mod = _import_moshi_engine(monkeypatch)
    seen = []

    def fake_get(url, timeout):
        seen.append((url, timeout))
        return _DummyResponse(200)

    monkeypatch.setattr(mod.requests, "get", fake_get)

    engine = mod.MoshiEngine(base_url="ws://127.0.0.1:8998/api/chat")

    assert engine.is_available is True
    assert seen == [("http://127.0.0.1:8998/health", 2)]


def test_moshi_engine_falls_back_to_readiness_and_root(monkeypatch):
    mod = _import_moshi_engine(monkeypatch)
    seen = []

    def fake_get(url, timeout):
        seen.append((url, timeout))
        if url.endswith("/health") or url.endswith("/readiness"):
            raise RuntimeError("temporary failure")
        return _DummyResponse(200)

    monkeypatch.setattr(mod.requests, "get", fake_get)

    engine = mod.MoshiEngine(base_url="http://127.0.0.1:8998/api/chat")

    assert engine.is_available is True
    assert seen == [
        ("http://127.0.0.1:8998/health", 2),
        ("http://127.0.0.1:8998/readiness", 2),
        ("http://127.0.0.1:8998", 2),
    ]


def test_moshi_engine_reports_unavailable_after_all_candidates_fail(monkeypatch):
    mod = _import_moshi_engine(monkeypatch)
    seen = []

    def fake_get(url, timeout):
        seen.append((url, timeout))
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mod.requests, "get", fake_get)

    engine = mod.MoshiEngine(base_url="http://127.0.0.1:8998")

    assert engine.is_available is False
    assert seen == [
        ("http://127.0.0.1:8998/health", 2),
        ("http://127.0.0.1:8998/readiness", 2),
        ("http://127.0.0.1:8998", 2),
    ]


def test_moshi_engine_normalizes_scheme_less_host_port(monkeypatch):
    mod = _import_moshi_engine(monkeypatch)
    seen = []

    def fake_get(url, timeout):
        seen.append((url, timeout))
        return _DummyResponse(200)

    monkeypatch.setattr(mod.requests, "get", fake_get)

    engine = mod.MoshiEngine(base_url="127.0.0.1:8998")

    assert engine.is_available is True
    assert seen == [("http://127.0.0.1:8998/health", 2)]
