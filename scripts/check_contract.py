"""Compare executable OpenAPI and reproducible generated TypeScript with tracked artifacts."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))
from mianshiya.main import app

base = root / "packages/api-client"
if json.loads((base / "openapi.json").read_text()) != app.openapi():
    raise SystemExit("STALE: OpenAPI snapshot; run make generate")
with tempfile.TemporaryDirectory(dir=base, prefix="contract-check-") as folder:
    output = Path(folder) / "schema.d.ts"
    result = subprocess.run(
        [
            "pnpm",
            "--dir",
            str(root / "apps/web"),
            "exec",
            "openapi-typescript",
            str(base / "openapi.json"),
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise SystemExit("FAIL: TypeScript schema generation")
    if output.read_text() != (base / "schema.d.ts").read_text():
        raise SystemExit("STALE: generated TypeScript; run make generate")
print("PASS: executable OpenAPI and generated TypeScript match")
