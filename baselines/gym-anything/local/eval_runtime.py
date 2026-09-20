"""Check local prerequisites and record unchanged official sandbox operations."""
from contextlib import contextmanager
import json
import subprocess
from pathlib import Path
import time
import urllib.error
import urllib.request

from local.eval_docker import PROXY_CHECK, UPSTREAM_PROXY

from agents.shared.agent_sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[1]
BASE_CACHE = ROOT / "local/runtime/qemu/evaluation-cache"


class RecordedDockerSandbox(DockerSandbox):
    @contextmanager
    def record(self, stage):
        started = time.time()
        event = dict(stage=stage, started=started, container=self.container_name)
        try:
            yield
        except Exception as error:
            event.update(error=type(error).__name__)
            if hasattr(error, "timeout"):
                event["timeout_seconds"] = error.timeout
            raise
        finally:
            event["elapsed_seconds"] = time.time() - started
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            with (self.logs_dir / "sandbox-events.jsonl").open("a") as log:
                log.write(json.dumps(event) + "\n")

    def start(self, gateway_port, gateway_token, container_env):
        with self.record("start"):
            return super().start(gateway_port, gateway_token, container_env)

    def exec(self, command, timeout_sec):
        with self.record("exec"):
            return super().exec(command, timeout_sec)

    def stop(self):
        with self.record("stop"):
            return super().stop()


class NetworkPreflightError(RuntimeError):
    """A transient connectivity failure; queue may probe again later."""


def check_host():
    docker_root = subprocess.check_output(["docker", "info", "--format", "{{.DockerRootDir}}"],
                                          text=True, timeout=15).strip()
    if docker_root != "/data1/evaluationclaw/docker":
        raise RuntimeError(f"Evaluation requires the dedicated Docker, got {docker_root}")
    limit = int(Path("/proc/sys/fs/inotify/max_user_instances").read_text())
    if limit < 1024:
        raise RuntimeError(f"inotify max_user_instances={limit}; this run requires the approved 1024 limit")
    if not (BASE_CACHE / "READY").is_file():
        raise RuntimeError("Run local/prepare_eval_base.py to verify the guest Docker proxy first")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": "http://" + UPSTREAM_PROXY}))
    for attempt in range(4):
        try:
            try:
                with opener.open("https://registry-1.docker.io/v2/", timeout=15) as response:
                    status = response.status
            except urllib.error.HTTPError as error:
                status = error.code
            if status != 401:
                raise RuntimeError(f"Unexpected Docker Hub registry response: {status}")
            subprocess.run(["docker", "exec", "gym-eval-proxy", "python3", "-c", PROXY_CHECK],
                           check=True, capture_output=True, timeout=30)
            break
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            if attempt == 3:
                raise NetworkPreflightError("Evaluation proxy preflight failed after four attempts") from error
            time.sleep(5)
    return dict(inotify_max_user_instances=limit, docker_root=docker_root,
                registry_status=status,
                evaluation_base=str(BASE_CACHE / "base_ubuntu_gnome.qcow2"),
                base_verification=json.loads((BASE_CACHE / "verification.json").read_text()))


def infrastructure_errors(run):
    events = [event for path in Path(run).glob("episodes/*/cli_harness/sandbox-events.jsonl")
              for line in path.read_text().splitlines()
              if (event := json.loads(line)).get("error") and event["stage"] in ("start", "stop")]
    preflight = Path(run) / "mount-preflight.json"
    if preflight.exists():
        result = json.loads(preflight.read_text())
        if result['returncode']:
            events.append(dict(stage='mount_preflight', **result))
    return events
