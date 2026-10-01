"""Run disposable local fixtures, capture safe reports, and clean up owned resources."""
import importlib.metadata
import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

BASE = Path(__file__).parent.resolve()
parser = argparse.ArgumentParser()
parser.add_argument("--skip-es", action="store_true", help="isolate topology/SQL/Redis diagnostics; does not complete S0")
args = parser.parse_args()
REPORT = BASE / ("report-topology.json" if args.skip_es else "report.json")
OWNED = []
PROCESSES = []
HANDLES = []
env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1", "MIANSHIYA_SPIKE": "1"}


def command(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def container(suffix, image, port, extra):
    name = f"mianshiya-s0-{suffix}-{os.getpid()}"
    args = ["docker", "run", "--rm", "--pull=never", "-d", "--name", name,
            "-p", f"127.0.0.1::{port}", *extra, image]
    command(args)
    OWNED.append(name)
    mapped = command(["docker", "port", name, f"{port}/tcp"])
    return int(mapped.rsplit(":", 1)[1])


def wait_http(url, timeout=600):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("local service readiness timed out; inspect fixture logs locally")


def start(args, logfile, extra=None):
    handle = (BASE / logfile).open("w")
    HANDLES.append(handle)
    process = subprocess.Popen(args, cwd=BASE, env={**env, **(extra or {})}, stdout=handle, stderr=subprocess.STDOUT)
    PROCESSES.append(process)
    return process


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def main():
    data = {"scope": "S0 fixture only; not product acceptance", "host": {
        "platform": platform.system(), "machine": platform.machine(), "cpu_count": os.cpu_count(),
        "memory_bytes": int(command(["sysctl", "-n", "hw.memsize"])) if platform.system() == "Darwin" else None,
    }, "versions": {"python": platform.python_version(), "node": command(["node", "--version"]),
                    "pnpm": command(["pnpm", "--version"])} }
    for package in ["fastapi", "uvicorn", "sqlalchemy", "psycopg", "redis", "elasticsearch", "httpx", "pytest"]:
        data["versions"][package] = importlib.metadata.version(package)
    images = {"postgres": "postgres:18-alpine", "redis": "redis:8-alpine", "elasticsearch": "docker.elastic.co/elasticsearch/elasticsearch:9.5.4"}
    data["images"] = {key: {"tag": tag, "id": command(["docker", "image", "inspect", tag, "--format", "{{.Id}}"])} for key, tag in images.items()}
    print("S0: starting isolated PostgreSQL and Redis" + ("" if args.skip_es else " and Elasticsearch"), flush=True)
    pg = container("pg", images["postgres"], 5432, ["--memory", "256m", "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_DB=mianshiya_s0"])
    redis = container("redis", images["redis"], 6379, ["--memory", "128m"])
    es = 1 if args.skip_es else container("es", images["elasticsearch"], 9200, ["--memory", "1g", "-e", "discovery.type=single-node", "-e", "xpack.security.enabled=false", "-e", "ES_JAVA_OPTS=-Xms512m -Xmx512m"])
    env.update({"S0_DATABASE_URL": f"postgresql+psycopg://postgres@127.0.0.1:{pg}/mianshiya_s0",
                "S0_REDIS_URL": f"redis://127.0.0.1:{redis}/0", "S0_ES_URL": f"http://127.0.0.1:{es}"})
    import psycopg
    pg_deadline = time.monotonic() + 180
    while True:
        try:
            with psycopg.connect(f"host=127.0.0.1 port={pg} dbname=mianshiya_s0 user=postgres", connect_timeout=2):
                break
        except psycopg.OperationalError:
            if time.monotonic() >= pg_deadline:
                raise RuntimeError("PostgreSQL fixture readiness failed") from None
            time.sleep(0.2)
    api_port, web_port = unused_port(), unused_port()
    env.update({"S0_API_ORIGIN": f"http://127.0.0.1:{api_port}", "S0_WEB_ORIGIN": f"http://127.0.0.1:{web_port}"})
    start([sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", str(api_port), "--no-access-log"], "api.log")
    wait_http(env["S0_API_ORIGIN"] + "/api/spike/health")
    print("S0: building Next.js production fixture", flush=True)
    with (BASE / "web-build.log").open("w") as log:
        build = subprocess.run(["pnpm", "--dir", str(BASE / "web"), "build"], env=env, stdout=log, stderr=subprocess.STDOUT)
    if build.returncode:
        raise RuntimeError("Next.js build failed; inspect web-build.log")
    types = subprocess.run(["pnpm", "--dir", str(BASE / "web"), "typecheck"], env=env, capture_output=True, text=True)
    if types.returncode:
        raise RuntimeError("TypeScript check failed")
    web = start(["node", str(BASE / "web/node_modules/next/dist/bin/next"), "start", str(BASE / "web"), "--hostname", "127.0.0.1", "--port", str(web_port)], "web.log")
    wait_http(env["S0_WEB_ORIGIN"] + "/api/spike/health")
    if not args.skip_es:
        wait_http(env["S0_ES_URL"])
    print("S0: running real-service behavioral tests", flush=True)
    selection = ["-k", "not chinese"] if args.skip_es else []
    tests = subprocess.run([sys.executable, "-m", "pytest", str(BASE / "test_spike.py"), "-q", "--tb=no", "-p", "no:cacheprovider", *selection], env=env, capture_output=True, text=True)
    (BASE / ("tests-topology.txt" if args.skip_es else "tests.txt")).write_text(tests.stdout)
    data["tests"] = {"exit_code": tests.returncode, "summary": tests.stdout.strip()}
    if tests.returncode:
        REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        raise RuntimeError("S0 behavioral tests failed; see tests.txt (no credential output)")
    import httpx
    samples = []
    for _ in range(3):
        values = []
        with httpx.Client(base_url=env["S0_WEB_ORIGIN"]) as client:
            client.post("/api/spike/login", json={"actor": "alice"}, headers={"Origin": env["S0_WEB_ORIGIN"]}).raise_for_status()
            for _ in range(30):
                started = time.perf_counter()
                response = client.get("/api/spike/session")
                response.raise_for_status()
                values.append((time.perf_counter() - started) * 1000)
        ordered = sorted(values)
        samples.append({"requests": 30, "concurrency": 1, "p50_ms": round(ordered[14], 2), "p95_ms": round(ordered[28], 2), "errors": 0})
    data["baseline"] = {"fixture": "two synthetic actors; Next.js API proxy → FastAPI → Redis + PostgreSQL", "runs": samples,
                        "limitation": "shared local machine; not representative product load or S8 performance result"}
    stop(web)
    print("S0: mutation test removes SSR cookie forwarding", flush=True)
    start(["node", str(BASE / "web/node_modules/next/dist/bin/next"), "start", str(BASE / "web"), "--hostname", "127.0.0.1", "--port", str(web_port)], "web-mutation.log", {"S0_DROP_SSR_COOKIE": "1"})
    wait_http(env["S0_WEB_ORIGIN"] + "/api/spike/health")
    mutated = subprocess.run([sys.executable, "-m", "pytest", str(BASE / "test_spike.py"), "-q", "--tb=no", "-p", "no:cacheprovider", "-k", "test_ssr_cookie_forwarding"], env=env, capture_output=True, text=True)
    (BASE / "mutation.txt").write_text(mutated.stdout)
    data["mutation"] = {"exit_code": mutated.returncode, "summary": mutated.stdout.strip(), "expected": "one failing test"}
    if mutated.returncode != 1 or "1 failed" not in mutated.stdout:
        raise RuntimeError("SSR mutation was not detected")
    data["next_build"] = "passed"
    data["typecheck"] = "passed"
    data["elasticsearch_test"] = "not run" if args.skip_es else "passed"
    data["cleanup"] = "owned containers/processes cleaned by finally"
    REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print("PASS: " + ("S0a (Elasticsearch excluded)" if args.skip_es else "S0") + " real-service tests, production Next.js build, typecheck, and SSR mutation", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        for process in reversed(PROCESSES):
            stop(process)
        for handle in HANDLES:
            handle.close()
        for name in reversed(OWNED):
            if "-es-" in name:
                raw = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
                events = []
                for line in (raw.stdout + "\n" + raw.stderr).splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("log.level") in {"ERROR", "FATAL"}:
                        events.append({"level": event.get("log.level"), "logger": event.get("log.logger"), "type": event.get("error.type")})
                (BASE / "es-diagnostics.json").write_text(json.dumps({"errors": events}, indent=2) + "\n")
            subprocess.run(["docker", "stop", "--timeout", "3", name], capture_output=True)
