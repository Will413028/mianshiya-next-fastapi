"""Serialize destructive operations on the dedicated integration fixture."""

import fcntl
from pathlib import Path


def acquire(path=None):
    path = path or Path(__file__).resolve().parents[1] / ".tools/integration.lock"
    path.parent.mkdir(exist_ok=True)
    handle = path.open("a")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SystemExit(
            "The isolated integration fixture is in use by another test or benchmark process"
        ) from None
    return handle
