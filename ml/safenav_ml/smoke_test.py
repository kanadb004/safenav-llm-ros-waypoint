"""Phase 0 smoke test: load a GGUF model with llama-cpp-python and run one grammar constrained
resolution. Usage: python ml/safenav_ml/smoke_test.py [models/phi3-mini-4k-instruct.Q4_K_M.gguf]
"""
import json
import sys
import time
from pathlib import Path

from llama_cpp import Llama, LlamaGrammar

ROOMS = ["charging_dock", "kitchen", "server_room", "reception", "meeting_room_a"]

GRAMMAR = r'''
root ::= "{" ws "\"room\"" ws ":" ws room-value "," ws "\"confidence\"" ws ":" ws confidence-value ws "}"
room-value ::= %s
confidence-value ::= [0-9] "." [0-9] [0-9]
ws ::= [ \t\n]*
''' % " | ".join('"\\"%s\\""' % r for r in ROOMS)


def main() -> int:
    model_path = Path(sys.argv[1] if len(sys.argv) > 1 else "models/phi3-mini-4k-instruct.Q4_K_M.gguf")
    t0 = time.time()
    llm = Llama(model_path=str(model_path), n_ctx=2048, n_threads=8, n_gpu_layers=-1, verbose=False)
    print(f"loaded {model_path.name} in {time.time() - t0:.1f}s")
    grammar = LlamaGrammar.from_string(GRAMMAR, verbose=False)
    system = ("You are a robot navigation assistant. Your only task is to identify which of the "
              "following locations the user wants to navigate to. Available locations: "
              + ", ".join(ROOMS) + ". Respond ONLY with valid JSON.")
    for cmd in ["go to the kitchen", "somewhere I can charge the robot", "go to the cafeteria"]:
        prompt = f"<|system|>\n{system}<|end|>\n<|user|>\n{cmd}<|end|>\n<|assistant|>\n"
        t0 = time.time()
        out = llm(prompt, max_tokens=64, temperature=0.0, grammar=grammar)
        text = out["choices"][0]["text"]
        obj = json.loads(text)
        assert obj["room"] in ROOMS, text
        print(f"{cmd!r:40} -> {text.strip()}  ({(time.time() - t0) * 1000:.0f} ms)")
    print("smoke test ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
