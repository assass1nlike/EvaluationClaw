"""Exercise upstream continuation and process cleanup with real subprocesses."""
import json
from pathlib import Path
import sys

import pytest

from extras.research.task_generation.propose_and_amplify.pipeline import propose_cc
from local.seed_batch import record_claude


@pytest.mark.parametrize('exit_code,is_error,timeout', [
    (0, False, False), (7, False, False), (0, True, False), (0, False, True),
])
def test_recording_preserves_upstream_exit_and_cleanup(tmp_path, exit_code, is_error, timeout):
    child_pid = tmp_path / 'child.pid'
    script = tmp_path / 'cli.py'
    script.write_text(
        'import json, subprocess, sys, time\n'
        'from pathlib import Path\n'
        'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        f'Path({str(child_pid)!r}).write_text(str(p.pid))\n'
        f'print(json.dumps({{"type": "result", "is_error": {is_error!r}}}), flush=True)\n'
        + ('time.sleep(60)\n' if timeout else f'sys.exit({exit_code})\n')
    )
    record_claude(propose_cc.run_claude, Path(sys.executable), [str(script)],
                 cwd=tmp_path, timeout=0.3 if timeout else 5, job=tmp_path, phase=1)
    status = json.loads((tmp_path / 'phase_1.result.json').read_text())
    assert status.get('timeout', False) is timeout
    assert status['result']['is_error'] is is_error
    assert status['returncode'] == (-15 if timeout else exit_code)
    state = Path('/proc') / child_pid.read_text() / 'stat'
    assert not state.exists() or state.read_text().split()[2] == 'Z'
