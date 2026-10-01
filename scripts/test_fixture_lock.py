import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixture_lock import acquire


class FixtureLockTest(unittest.TestCase):
    def child(self, path):
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; from fixture_lock import acquire; acquire(Path(sys.argv[1]))",
                str(path),
            ],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_overlapping_process_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.lock"
            with acquire(path):
                child = self.child(path)
                self.assertNotEqual(child.returncode, 0)
                self.assertIn("fixture is in use", child.stderr)

    def test_released_lock_allows_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.lock"
            acquire(path).close()
            self.assertEqual(self.child(path).returncode, 0)


if __name__ == "__main__":
    unittest.main()
