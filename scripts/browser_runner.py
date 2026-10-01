"""Own and stop only the API/Next processes used by the browser gate."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def ready(url, process):
    deadline = time.monotonic() + 90
    async with httpx.AsyncClient(timeout=10) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Owned browser service exited")
            try:
                if (await client.get(url)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
    raise RuntimeError("Owned browser service readiness timed out")


async def main():
    api_port, web_port = available_port(), available_port()
    env = {
        **os.environ,
        "API_ORIGIN": f"http://127.0.0.1:{api_port}",
        "WEB_ORIGIN": f"http://127.0.0.1:{web_port}",
        "E2E_ORIGIN": f"http://127.0.0.1:{web_port}",
    }
    processes, logs = [], []
    try:
        for name, command, cwd in (
            (
                "api",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "mianshiya.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--no-access-log",
                    "--no-proxy-headers",
                ],
                root / "apps/api",
            ),
            (
                "web",
                [
                    "pnpm",
                    "--dir",
                    str(root / "apps/web"),
                    "exec",
                    "next",
                    "start",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(web_port),
                ],
                root,
            ),
        ):
            log = (root / f"reports/browser-{name}.log").open("w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            )
        await ready(env["API_ORIGIN"] + "/api/v1/health", processes[0])
        await ready(env["E2E_ORIGIN"], processes[1])
        result = await asyncio.to_thread(subprocess.run, ["make", "-C", str(root), "e2e"], env=env)
        if result.returncode:
            raise SystemExit(result.returncode)
    finally:
        import signal

        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.to_thread(process.wait, timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    await asyncio.to_thread(process.wait, timeout=10)
        for log in logs:
            log.close()


if __name__ == "__main__":
    asyncio.run(main())
