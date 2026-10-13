"""Host pytest for the backend seam (PLAN.md section 8.2). Both backends are driven against
fakes so this needs neither a loaded GGUF model nor a running llama-server."""

import os
import sys

import pytest

_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from semantic_waypoint_planner import backends  # noqa: E402


class _FakeLlamaGrammar:
    @classmethod
    def from_string(cls, grammar_str):
        return ("compiled", grammar_str)


class _FakeLlama:
    def __init__(self, model_path, n_ctx, n_threads, n_gpu_layers, verbose):
        self.model_path = model_path
        self.calls = []
        self.reset_count = 0

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [{"text": '{"room": "kitchen", "relation": "none", "confidence": 0.9}'}],
            "usage": {"prompt_tokens": 42},
        }

    def reset(self):
        self.reset_count += 1


class _FakeLlamaCppModule:
    Llama = _FakeLlama
    LlamaGrammar = _FakeLlamaGrammar


@pytest.fixture()
def fake_llama_cpp(monkeypatch):
    monkeypatch.setattr(backends, "llama_cpp", _FakeLlamaCppModule)
    return _FakeLlamaCppModule


def test_inprocess_backend_complete_returns_text_latency_tokens(fake_llama_cpp):
    backend = backends.InProcessBackend("model.gguf")
    text, latency_ms, prompt_eval_tokens = backend.complete("prompt text", grammar=None)
    assert text == '{"room": "kitchen", "relation": "none", "confidence": 0.9}'
    assert latency_ms >= 0.0
    assert prompt_eval_tokens == 42


def test_inprocess_backend_passes_grammar_through(fake_llama_cpp):
    backend = backends.InProcessBackend("model.gguf")
    grammar_str = 'root ::= "x"'
    backend.complete("prompt text", grammar=grammar_str)
    call = backend._llm.calls[0]
    assert call["grammar"] == ("compiled", grammar_str)


def test_inprocess_backend_no_grammar_key_when_grammar_off(fake_llama_cpp):
    backend = backends.InProcessBackend("model.gguf")
    backend.complete("prompt text", grammar=None)
    call = backend._llm.calls[0]
    assert "grammar" not in call


def test_inprocess_backend_caches_compiled_grammar(fake_llama_cpp):
    backend = backends.InProcessBackend("model.gguf")
    grammar_str = 'root ::= "x"'
    backend.complete("a", grammar=grammar_str)
    backend.complete("b", grammar=grammar_str)
    assert len(backend._grammar_cache) == 1


def test_inprocess_backend_reset_delegates(fake_llama_cpp):
    backend = backends.InProcessBackend("model.gguf")
    backend.reset()
    assert backend._llm.reset_count == 1


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_http_backend_posts_completion_and_parses_response(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse({"content": '{"room": "kitchen"}', "tokens_evaluated": 17})

    monkeypatch.setattr(backends.requests, "post", fake_post)
    backend = backends.HttpBackend("http://host.docker.internal:8080")
    text, latency_ms, prompt_eval_tokens = backend.complete(
        "prompt text", grammar='root ::= "x"', max_tokens=64, temperature=0.0, stop=["<|end|>"]
    )
    assert text == '{"room": "kitchen"}'
    assert prompt_eval_tokens == 17
    assert captured["url"] == "http://host.docker.internal:8080/completion"
    assert captured["json"]["grammar"] == 'root ::= "x"'
    assert captured["json"]["n_predict"] == 64
    assert captured["json"]["stop"] == ["<|end|>"]


def test_http_backend_omits_grammar_when_none(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse({"content": "", "tokens_evaluated": 0})

    monkeypatch.setattr(backends.requests, "post", fake_post)
    backend = backends.HttpBackend("http://host.docker.internal:8080")
    backend.complete("prompt text", grammar=None)
    assert "grammar" not in captured["json"]


def test_build_backend_inprocess(fake_llama_cpp):
    backend = backends.build_backend("inprocess", "model.gguf")
    assert isinstance(backend, backends.InProcessBackend)


def test_build_backend_http():
    backend = backends.build_backend("http", "model.gguf", backend_url="http://example:8080")
    assert isinstance(backend, backends.HttpBackend)
    assert backend.base_url == "http://example:8080"


def test_build_backend_unknown_raises():
    with pytest.raises(ValueError):
        backends.build_backend("carrier_pigeon", "model.gguf")
