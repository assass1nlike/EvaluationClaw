"""Select the administrator-provided Docker endpoint for this process only."""
import os
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time

SOCKET = Path("/run/evaluationclaw/docker.sock")
ROOT = Path(__file__).resolve().parents[1]
AGENT_IMAGE = "gym-anything-agent-sandbox-claude:1306f4dda6e1"
UPSTREAM_PROXY = os.environ.get("GYM_EVAL_UPSTREAM_PROXY", "127.0.0.1:17891")
PROXY_CHECK = """import urllib.request, urllib.error
opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': 'http://127.0.0.1:17891'}))
try:
    with opener.open('https://registry-1.docker.io/v2/', timeout=15) as response:
        status = response.status
except urllib.error.HTTPError as error:
    status = error.code
assert status == 401, status
print(status)
"""


def use_dedicated_docker():
    os.environ["DOCKER_HOST"] = "unix://" + str(SOCKET)
    for name in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        os.environ.pop(name, None)
    if not SOCKET.exists():
        raise RuntimeError(f"Dedicated Docker socket is missing: {SOCKET}")
    if not os.access(SOCKET, os.R_OK | os.W_OK):
        if os.environ.get("GYM_EVAL_GROUP_REFRESHED"):
            raise RuntimeError("The evaluationclaw group cannot access its Docker socket")
        os.environ["GYM_EVAL_GROUP_REFRESHED"] = "1"
        os.execvp("sg", ["sg", "evaluationclaw", "-c", shlex.join([sys.executable, *sys.argv])])


def setup_proxy():
    directory = ROOT / "local/runtime/eval-proxy"
    directory.mkdir(mode=0o700, exist_ok=True)
    pid_file = directory / "host.json"
    running = False
    if pid_file.exists():
        state = json.loads(pid_file.read_text())
        pid = state["pid"]
        command_file = Path(f"/proc/{pid}/cmdline")
        if command_file.exists():
            running = str(ROOT / "local/eval_proxy.py").encode() in command_file.read_bytes().split(b"\0")
        if running and state["upstream"] != UPSTREAM_PROXY:
            raise RuntimeError("Stop the evaluation relay before changing GYM_EVAL_UPSTREAM_PROXY")
    if not running:
        with (directory / "host.log").open("a") as log:
            process = subprocess.Popen([
                sys.executable, str(ROOT / "local/eval_proxy.py"),
                "--listen", "10.253.240.1:17891", "--upstream", UPSTREAM_PROXY,
            ], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(20):
            if process.poll() is not None:
                raise RuntimeError("Host proxy relay failed; see local/runtime/eval-proxy/host.log")
            try:
                with socket.create_connection(("10.253.240.1", 17891), timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            process.terminate()
            raise RuntimeError("Host proxy relay did not start")
        pid_file.write_text(json.dumps({"pid": process.pid, "listen": "10.253.240.1:17891",
                                       "upstream": UPSTREAM_PROXY}) + "\n")
    result = subprocess.run(["docker", "inspect", "gym-eval-proxy"], capture_output=True, text=True)
    if result.returncode == 0:
        container = json.loads(result.stdout)[0]
        if container["Config"].get("Labels", {}).get("gym-anything-role") != "evaluation-proxy":
            raise RuntimeError("gym-eval-proxy belongs to another configuration")
        if not container["State"]["Running"]:
            subprocess.run(["docker", "start", "gym-eval-proxy"], check=True)
        return
    subprocess.run([
        "docker", "run", "-d", "--name", "gym-eval-proxy", "--restart", "unless-stopped",
        "--label", "gym-anything-role=evaluation-proxy", "--network", "host", "--read-only",
        "--memory", "512m", "--memory-swap", "1g",
        "--cap-drop", "ALL", "--user", f"{os.getuid()}:{os.getgid()}",
        "--mount", f"type=bind,src={ROOT / 'local/eval_proxy.py'},dst=/relay.py,readonly",
        AGENT_IMAGE, "python3", "/relay.py", "--listen", "127.0.0.1:17891",
        "--upstream", "10.253.240.1:17891",
    ], check=True)


if __name__ == "__main__":
    use_dedicated_docker()
    setup_proxy()
    subprocess.run(["docker", "exec", "gym-eval-proxy", "python3", "-c", PROXY_CHECK], check=True, timeout=30)
