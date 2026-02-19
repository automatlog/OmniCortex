import asyncio
from types import SimpleNamespace

import pytest


class _DummyTransport:
    def get_extra_info(self, _name):
        return ("127.0.0.1", 5555)


class _DummyRequest:
    def __init__(self, query=None, headers=None):
        self.query = query or {}
        self.headers = headers or {}
        self.remote = "127.0.0.1"
        self.transport = _DummyTransport()

    def __getitem__(self, _key):
        raise AssertionError("Direct request indexing should not be used")


def _run(coro):
    return asyncio.run(coro)


def test_create_loss_report_handles_text_and_audio_targets_without_index_error():
    torch = pytest.importorskip("torch")
    lm_mod = pytest.importorskip("moshi.moshi.models.lm")
    create_loss_report = lm_mod.create_loss_report

    class _FakeLM:
        dep_q = 2
        zero_token_id = 0
        text_initial_token_id = 99
        initial_token_id = 88

    batch_size = 2
    dep_q = _FakeLM.dep_q
    text_card = 16
    audio_card = 32

    state_cache = torch.zeros((batch_size, dep_q + 1, 3), dtype=torch.long)
    text_logits = torch.randn((batch_size, 1, 1, text_card), dtype=torch.float32)
    audio_logits = torch.randn((batch_size, dep_q, audio_card), dtype=torch.float32)
    target = torch.tensor(
        [
            [[1], [2], [3]],
            [[4], [5], [6]],
        ],
        dtype=torch.long,
    )
    sampled_text_token = torch.tensor([1, 4], dtype=torch.long)
    sampled_audio_tokens = torch.tensor([[2, 3], [5, 6]], dtype=torch.long)

    report = create_loss_report(
        state_cache=state_cache,
        lm_model=_FakeLM(),
        text_logits=text_logits,
        audio_logits=audio_logits,
        target=target,
        sampled_text_token=sampled_text_token,
        sampled_audio_tokens=sampled_audio_tokens,
        target_position=0,
    )

    assert report["forced_tokens"].shape == (batch_size, dep_q + 1)
    assert report["model_tokens"].shape == (batch_size, dep_q + 1)
    assert report["ranks_of_forced"].shape == (batch_size, dep_q + 1)
    assert report["losses"].shape == (batch_size, dep_q + 1)
    assert torch.isfinite(report["losses"]).all()


def test_handle_chat_rejects_unauthorized_when_token_is_configured(monkeypatch):
    web = pytest.importorskip("aiohttp.web")
    server_mod = pytest.importorskip("moshi.moshi.server")
    handle_chat = server_mod.ServerState.handle_chat

    monkeypatch.setenv("MOSHI_API_TOKEN", "secret-token")
    request = _DummyRequest(query={})

    response = _run(handle_chat(SimpleNamespace(), request))

    assert isinstance(response, web.Response)
    assert response.status == 401


def test_handle_chat_reads_seed_from_query_not_request_mapping(monkeypatch):
    pytest.importorskip("aiohttp.web")
    server_mod = pytest.importorskip("moshi.moshi.server")
    handle_chat = server_mod.ServerState.handle_chat

    class _DummyWS:
        async def prepare(self, _request):
            return None

    class _DummyLog:
        def log(self, *_args, **_kwargs):
            return None

    monkeypatch.setenv("MOSHI_API_TOKEN", "secret-token")
    monkeypatch.setattr(server_mod.web, "WebSocketResponse", _DummyWS)
    monkeypatch.setattr(server_mod.ColorizedLog, "randomize", staticmethod(lambda: _DummyLog()))

    request = _DummyRequest(query={"token": "secret-token", "seed": "not-an-int"})
    state = SimpleNamespace(voice_prompt_dir=None)

    with pytest.raises(server_mod.web.HTTPBadRequest):
        _run(handle_chat(state, request))
