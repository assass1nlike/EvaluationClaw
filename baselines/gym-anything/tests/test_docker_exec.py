import subprocess
import sys
import unittest
from unittest.mock import patch

from gym_anything.runtime.runners.docker import DockerRunner, _sh
from gym_anything.specs import EnvSpec


class DockerExecTests(unittest.TestCase):
    def test_hook_timeout_reaches_subprocess(self):
        runner = DockerRunner(EnvSpec.from_dict({"id": "timeout-test@1"}))
        result = subprocess.CompletedProcess([], 0)
        with patch("subprocess.run", return_value=result) as execute:
            self.assertEqual(runner.exec("true", timeout=17, use_pty=False), 0)
        self.assertEqual(execute.call_args.kwargs["timeout"], 17)

    def test_command_timeout_is_reported(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            _sh([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)
