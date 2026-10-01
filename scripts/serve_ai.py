"""Run the isolated Ollama binary; capture startup output without disclosing credentials."""

import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = root / ".tools"
binary = base / "ollama/ollama"
if not binary.exists():
    raise SystemExit("Install the verified official Ollama standalone runtime in .tools/ollama")
with (base / "ollama-runtime.log").open("w") as log:
    process = subprocess.Popen(
        [str(binary), "serve"],
        stdout=log,
        stderr=subprocess.STDOUT,
        env={
            **os.environ,
            "OLLAMA_HOST": "127.0.0.1:11439",
            "OLLAMA_MODELS": str(base / "models"),
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_CONTEXT_LENGTH": "32768",
        },
    )
    (base / "ollama.pid").write_text(str(process.pid) + "\n")
    print("Local AI process started; diagnostics captured locally", flush=True)
    try:
        raise SystemExit(process.wait())
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
