"""Inference backend seam (PLAN.md section 8.2, D27/D28).

``ResolverCore`` talks to one of these instead of llama-cpp-python directly, so it can run
against an in-process model (host development, unit tests) or a ``llama-server`` process over
HTTP (batch runs on the Metal host, and the deployment shape on Jetson hardware) with no other
code change. Both backends are handed the identical GBNF grammar string.
"""

from __future__ import annotations

import time
from typing import Optional, Sequence, Tuple

try:
    import llama_cpp
except ImportError:  # pragma: no cover - exercised only when llama_cpp is absent
    llama_cpp = None

try:
    import requests
except ImportError:  # pragma: no cover - exercised only when requests is absent
    requests = None


class Backend:
    """``complete(prompt, grammar, **params) -> (text, latency_ms, prompt_eval_tokens)``."""

    def complete(
        self,
        prompt: str,
        grammar: Optional[str],
        max_tokens: int = 256,
        temperature: float = 0.1,
        stop: Optional[Sequence[str]] = None,
    ) -> Tuple[str, float, int]:
        raise NotImplementedError

    def reset(self) -> None:
        """Clear any per-session state (KV cache) between graph reloads. No-op by default."""


class InProcessBackend(Backend):
    """llama-cpp-python, in the same process as the resolver node (v1 behaviour, D27)."""

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 2048,
        n_threads: int = 4,
        n_gpu_layers: int = -1,
    ):
        if llama_cpp is None:
            raise ImportError("llama_cpp is required to construct an InProcessBackend")
        self._llm = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        self._grammar_cache: dict = {}

    def _compiled_grammar(self, grammar: str):
        compiled = self._grammar_cache.get(grammar)
        if compiled is None:
            compiled = llama_cpp.LlamaGrammar.from_string(grammar)
            self._grammar_cache[grammar] = compiled
        return compiled

    def complete(
        self,
        prompt: str,
        grammar: Optional[str],
        max_tokens: int = 256,
        temperature: float = 0.1,
        stop: Optional[Sequence[str]] = None,
    ) -> Tuple[str, float, int]:
        kwargs = dict(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=list(stop) if stop else [],
        )
        if grammar:
            kwargs["grammar"] = self._compiled_grammar(grammar)
        start = time.monotonic()
        completion = self._llm.create_completion(**kwargs)
        latency_ms = (time.monotonic() - start) * 1000.0
        text = completion["choices"][0]["text"]
        prompt_eval_tokens = completion.get("usage", {}).get("prompt_tokens", 0)
        return text, latency_ms, prompt_eval_tokens

    def reset(self) -> None:
        self._llm.reset()


class HttpBackend(Backend):
    """``llama-server`` (llama.cpp's own binary) over HTTP (D28).

    Same GGUF, same GBNF string sent verbatim as the ``grammar`` field of a POST to
    ``/completion``. This is the backend used for batch benchmark runs against the host Metal
    server, and the shape that deploys unchanged to the Jetson (localhost instead of
    ``host.docker.internal``).
    """

    def __init__(self, base_url: str = "http://host.docker.internal:8080", timeout_s: float = 120.0):
        if requests is None:
            raise ImportError("requests is required to construct an HttpBackend")
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def complete(
        self,
        prompt: str,
        grammar: Optional[str],
        max_tokens: int = 256,
        temperature: float = 0.1,
        stop: Optional[Sequence[str]] = None,
    ) -> Tuple[str, float, int]:
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "cache_prompt": True,
        }
        if grammar:
            payload["grammar"] = grammar
        if stop:
            payload["stop"] = list(stop)

        start = time.monotonic()
        response = requests.post(f"{self.base_url}/completion", json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        latency_ms = (time.monotonic() - start) * 1000.0
        data = response.json()
        text = data.get("content", "")
        prompt_eval_tokens = data.get("tokens_evaluated", 0)
        return text, latency_ms, prompt_eval_tokens

    def reset(self) -> None:
        # llama-server keeps its own KV/slot state server side; nothing to reset client side.
        pass


def build_backend(
    backend: str,
    model_path: str,
    n_ctx: int = 2048,
    n_threads: int = 4,
    n_gpu_layers: int = -1,
    backend_url: str = "http://host.docker.internal:8080",
) -> Backend:
    if backend == "inprocess":
        return InProcessBackend(model_path, n_ctx=n_ctx, n_threads=n_threads, n_gpu_layers=n_gpu_layers)
    if backend == "http":
        return HttpBackend(backend_url)
    raise ValueError(f"unknown backend: {backend!r} (expected 'inprocess' or 'http')")
