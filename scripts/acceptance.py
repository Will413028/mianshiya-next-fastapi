"""Run declared checks; never turn a missing check into a pass."""

import argparse
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--step", required=True, choices=["S" + str(i) for i in range(13)])
args = parser.parse_args()
checks = ["check", "integration"]
if args.step in {"S1", "S3", "S4", "S5", "S6", "S10", "S12"}:
    checks.append("e2e")
for check in checks:
    result = subprocess.run(["make", "-C", str(root), check])
    if result.returncode:
        raise SystemExit(result.returncode)
if args.step in {"S7", "S8", "S9", "S10", "S12"}:
    raise SystemExit(
        "Stage-specific ES/load/fault/live-provider evidence must also pass; generic checks alone cannot complete this step."
    )
