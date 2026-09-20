"""API recovery must preserve the session and never retry an ordinary task failure."""
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from local.eval_api_retry import run


class RetryTests(unittest.TestCase):
    def exercise(self, reasons):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        binary = root / "fake-cli"
        binary.write_text("#!/usr/bin/env python3\n" +
            "import sys,json\nfrom pathlib import Path\n" +
            f"root=Path({str(root)!r}); reasons={reasons!r}\n" +
            "calls=root/'calls.jsonl'\n" +
            "n=len(calls.read_text().splitlines()) if calls.exists() else 0\n" +
            "with calls.open('a') as f: f.write(json.dumps({'args':sys.argv[1:],'prompt':sys.stdin.read()})+'\\n')\n" +
            "print(json.dumps({'type':'result','session_id':'session-a','terminal_reason':reasons[min(n,len(reasons)-1)]}))\n")
        binary.chmod(0o755)
        run(["--print", "--effort", "high"], "original task", root, str(binary), delay=0)
        return [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]

    def test_recovers_same_session(self):
        calls = self.exercise(["api_error", "completed"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["prompt"], "original task")
        self.assertEqual(calls[1]["args"], ["--print", "--effort", "high", "--resume", "session-a"])

    def test_three_retries(self):
        self.assertEqual(len(self.exercise(["api_error"])), 4)

    def test_task_failure_is_not_retried(self):
        self.assertEqual(len(self.exercise(["error_max_turns"])), 1)

    def test_large_image_event_on_nonblocking_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / "cli"
            cli.write_text("#!/usr/bin/env python3\nimport json,sys\nsys.stdin.read()\n"
                           "print(json.dumps({'type':'result','terminal_reason':'completed','image':'a'*300000}))\n")
            cli.chmod(0o755)
            code = ("import os\nfrom pathlib import Path\nfrom local.eval_api_retry import run\n"
                    f"os.set_blocking(1,False)\nrun([], 'task', Path({directory!r}), {str(cli)!r})\n")
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)["image"]), 300000)


if __name__ == "__main__":
    unittest.main()
