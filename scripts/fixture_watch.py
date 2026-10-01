"""Keep this run's explicitly owned disposable fixtures usable; log transient pauses."""

import json
import subprocess
import time

names = ["mianshiya-verify-pg", "mianshiya-verify-redis", "mianshiya-verify-es"]
while True:
    for name in names:
        result = subprocess.run(
            ["docker", "inspect", name, "--format", "{{json .State}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            continue
        state = json.loads(result.stdout)
        if state["Paused"]:
            subprocess.run(["docker", "unpause", name], capture_output=True)
            print("resumed owned fixture: " + name, flush=True)
    time.sleep(2)
