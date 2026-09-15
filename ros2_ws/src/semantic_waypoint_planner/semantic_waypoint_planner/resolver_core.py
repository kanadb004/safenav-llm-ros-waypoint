"""ROS free resolver core: fast path, grammar constrained LLM resolution, ranking, features,
and the calibrator hook (PLAN.md Phase 3 scope, section 12.7/12.8).
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .grammar import build_grammar
from .graph import AnnotationGraph
from .prompt import DEFAULT_FEWSHOT_PATH, DEFAULT_TEMPLATE_PATH, PromptBuilder

try:
    import llama_cpp
except ImportError:  # pragma: no cover - exercised only when llama_cpp is absent
    llama_cpp = None

VERB_PHRASES = ["go to", "navigate to", "head to", "take me to", "move to"]
_WS_RE = re.compile(r"\s+")


def normalize_command(command: str) -> str:
    return _WS_RE.sub(" ", command.strip().lower())


def fast_path_match(graph: AnnotationGraph, command: str) -> Optional[str]:
    """Exact canonical-name or alias match, with a fixed leading verb phrase stripped."""
    norm = normalize_command(command)
    canonical = graph.resolve_alias(norm)
    if canonical:
        return canonical
    for room in graph.rooms:
        if norm == room.name.replace("_", " "):
            return room.name
    for verb in VERB_PHRASES:
        prefix = verb + " "
        if not norm.startswith(prefix):
            continue
        rest = norm[len(prefix):]
        if rest.startswith("the "):
            rest = rest[4:]
        canonical = graph.resolve_alias(rest)
        if canonical:
            return canonical
        for room in graph.rooms:
            if rest == room.name.replace("_", " "):
                return room.name
    return None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def min_edit_distance(resolved_name: Optional[str], aliases: List[str], command_norm: str) -> int:
    """Minimum Levenshtein distance between the resolved name (or an alias) and any equal
    length window of ``command_norm`` (PLAN.md section 12.8, feature 5)."""
    if not resolved_name or resolved_name == "none":
        return len(command_norm)
    candidates = [resolved_name.replace("_", " ")] + list(aliases)
    best = None
    for cand in candidates:
        length = len(cand)
        if length == 0:
            continue
        if length > len(command_norm):
            distance = _levenshtein(cand, command_norm)
        else:
            distance = min(
                _levenshtein(cand, command_norm[i:i + length])
                for i in range(len(command_norm) - length + 1)
            )
        best = distance if best is None else min(best, distance)
    return best if best is not None else len(command_norm)


@dataclass
class ResolveResult:
    room: str
    raw_confidence: float
    reasoning: str
    token_entropy: float
    room_ranking: List[Tuple[str, float]]
    latency_ms: float
    mode: str
    out_of_graph: bool
    raw_text: str
    calibrated_confidence: float = 0.0
    calibrator_loaded: bool = False
    prompt_eval_tokens: int = 0


class Calibrator:
    """Platt scaled logistic regression on the five section-12.8 features. Identity until
    ``config/calibrator.json`` (written by Phase 7) is present."""

    def __init__(self, config_path: Optional[str] = None):
        self.loaded = False
        self.threshold = 0.72
        self._mean: List[float] = []
        self._scale: List[float] = []
        self._weights: List[float] = []
        self._bias = 0.0
        if config_path:
            self.load(config_path)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            self.loaded = False
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._mean = list(data["scaler_mean"])
        self._scale = list(data["scaler_scale"])
        self._weights = list(data["weights"])
        self._bias = float(data["bias"])
        self.threshold = float(data.get("threshold", 0.72))
        self.loaded = True

    def calibrate(self, raw_confidence: float, features: List[float]) -> float:
        if not self.loaded:
            return raw_confidence
        z = self._bias
        for w, x, mean, scale in zip(self._weights, features, self._mean, self._scale):
            denom = scale if scale != 0 else 1.0
            z += w * (x - mean) / denom
        return 1.0 / (1.0 + math.exp(-z))


class ResolverCore:
    """Loads Phi-3 mini once, resolves commands against the closed annotation graph."""

    def __init__(
        self,
        model_path: str,
        graph: AnnotationGraph,
        n_ctx: int = 2048,
        n_threads: int = 4,
        temperature: float = 0.1,
        max_tokens: int = 256,
        fewshot_count: int = 0,
        prompt_template: str = DEFAULT_TEMPLATE_PATH,
        fewshot_path: str = DEFAULT_FEWSHOT_PATH,
        allow_none: bool = True,
        calibrator_path: Optional[str] = None,
        n_gpu_layers: int = -1,
    ):
        if llama_cpp is None:
            raise ImportError("llama_cpp is required to construct a ResolverCore")
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.fewshot_count = fewshot_count
        self.prompt_template = prompt_template
        self.fewshot_path = fewshot_path
        self.allow_none = allow_none
        self.calibrator = Calibrator(calibrator_path)
        self.last_prefix_tokens = 0

        self._llm = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        self.set_graph(graph)

    def set_graph(self, graph: AnnotationGraph) -> None:
        """(Re)build the prompt builder and grammar for a new/updated annotation graph.
        Called at startup and whenever ``/annotation_graph_updated`` fires."""
        self.graph = graph
        self.prompt_builder = PromptBuilder(
            graph, self.prompt_template, self.fewshot_path, self.fewshot_count
        )
        self._grammar_str = build_grammar(graph.canonical_names, allow_none=self.allow_none)
        self._grammar = llama_cpp.LlamaGrammar.from_string(self._grammar_str)
        self._llm.reset()

    @property
    def grammar_str(self) -> str:
        return self._grammar_str

    def resolve(
        self,
        command: str,
        candidates: Optional[List[str]] = None,
        grammar_on: bool = True,
        fast_path: bool = True,
        max_tokens: Optional[int] = None,
    ) -> ResolveResult:
        start = time.monotonic()
        candidates = candidates or self.graph.canonical_names

        fast_room = fast_path_match(self.graph, command) if fast_path else None
        if fast_room is not None:
            latency_ms = (time.monotonic() - start) * 1000.0
            result = ResolveResult(
                room=fast_room,
                raw_confidence=0.99,
                reasoning="",
                token_entropy=0.0,
                room_ranking=[(fast_room, 1.0)],
                latency_ms=latency_ms,
                mode="fast_path",
                out_of_graph=False,
                raw_text="",
            )
            self._apply_calibrator(result, command)
            return result

        return self._resolve_llm(command, candidates, grammar_on, start, max_tokens)

    def _resolve_llm(
        self,
        command: str,
        candidates: List[str],
        grammar_on: bool,
        start: float,
        max_tokens: Optional[int] = None,
    ) -> ResolveResult:
        prompt = self.prompt_builder.build_prompt(command)
        kwargs = dict(
            prompt=prompt,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            temperature=self.temperature,
            stop=["<|end|>"],
        )
        if grammar_on:
            kwargs["grammar"] = self._grammar

        completion = self._llm.create_completion(**kwargs)
        latency_ms = (time.monotonic() - start) * 1000.0
        self.last_prefix_tokens = getattr(self._llm, "n_tokens", 0)

        choice = completion["choices"][0]
        raw_text = choice["text"]
        mode = "llm_grammar" if grammar_on else "llm_free"

        room, raw_confidence = self._parse_answer(raw_text)
        out_of_graph = False
        if not grammar_on:
            # A garbled/unparseable answer (room is None) is just as much an escape from the
            # closed set as a well-formed but unknown name; grammar_on structurally rules out
            # both, so both count here.
            out_of_graph = room is None or (room != "none" and room not in self.graph.canonical_names)

        token_entropy, room_ranking = self._score_candidates(
            command, room or "none", raw_confidence, candidates
        )

        result = ResolveResult(
            room=room or "none",
            raw_confidence=raw_confidence,
            reasoning="" if grammar_on else raw_text,
            token_entropy=token_entropy,
            room_ranking=room_ranking,
            latency_ms=latency_ms,
            mode=mode,
            out_of_graph=out_of_graph,
            raw_text=raw_text,
            prompt_eval_tokens=completion.get("usage", {}).get("prompt_tokens", 0),
        )
        self._apply_calibrator(result, command)
        return result

    def features(self, result: ResolveResult, command: str, n_candidates: int) -> List[float]:
        room = None if result.room == "none" else result.room
        aliases = self.graph.get_room(room).aliases if room and self.graph.get_room(room) else []
        return features(result, command, n_candidates, aliases)

    def _apply_calibrator(self, result: ResolveResult, command: str) -> None:
        feature_vector = self.features(result, command, len(self.graph.canonical_names))
        result.calibrated_confidence = self.calibrator.calibrate(result.raw_confidence, feature_vector)
        result.calibrator_loaded = self.calibrator.loaded

    @staticmethod
    def _parse_answer(raw_text: str) -> Tuple[Optional[str], float]:
        try:
            data = json.loads(raw_text.strip())
            return data.get("room"), float(data.get("confidence", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            match = re.search(r'"room"\s*:\s*"([^"]*)"', raw_text)
            room = match.group(1) if match else None
            conf_match = re.search(r'"confidence"\s*:\s*([0-9.]+)', raw_text)
            confidence = float(conf_match.group(1)) if conf_match else 0.0
            return room, confidence

    def _score_candidates(
        self, command: str, chosen_room: str, raw_confidence: float, candidates: List[str]
    ) -> Tuple[float, List[Tuple[str, float]]]:
        """Approximate room-level ranking and entropy without a second model pass.

        PLAN.md allows falling back to "entropy of the grammar masked next token distribution
        at the first room token" if full batched candidate scoring is not feasible. In practice
        even that single extra step requires `logits_all=True` in llama-cpp-python, which forces
        the engine to compute vocabulary logits for *every* prompt token instead of just the
        last one; with the ~30 candidate, few-shot prompt used here that turned one resolution
        from ~10s into multiple minutes (see the Phase 3 report). Reusing the model's own
        reported ``confidence`` for entropy and lexical distance for the rest of the ranking
        needs no extra inference at all, and is documented as a further deviation.
        """
        norm_command = normalize_command(command)
        p = min(max(raw_confidence, 1e-6), 1 - 1e-6)
        entropy = -(p * math.log(p) + (1 - p) * math.log(1 - p))

        scores: Dict[str, float] = {}
        for name in candidates:
            if name == chosen_room:
                scores[name] = raw_confidence
            else:
                room = self.graph.get_room(name)
                aliases = room.aliases if room else []
                distance = min_edit_distance(name, aliases, norm_command)
                scores[name] = (1.0 - raw_confidence) / (1.0 + distance)

        total = sum(scores.values()) or 1.0
        probs = {k: v / total for k, v in scores.items()}
        ranking = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return entropy, ranking


def features(
    result: ResolveResult, command: str, n_candidates: int, aliases: Optional[List[str]] = None
) -> List[float]:
    """Section 12.8 feature vector, in order."""
    room = None if result.room == "none" else result.room
    edit_distance = min_edit_distance(room, aliases or [], normalize_command(command))
    return [
        result.raw_confidence,
        result.token_entropy,
        float(n_candidates),
        float(len(normalize_command(command))),
        float(edit_distance),
    ]
