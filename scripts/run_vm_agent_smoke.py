r"""Run a minimal EvaluationClaw agent task inside a real QEMU VM.

The script downloads an Ubuntu cloud image to D:\localwork\vm_backends\smoke,
injects a tiny HTTP desktop bridge with cloud-init, starts the VM through
EvalClaw's local QEMU VM provider, and runs one agent_interaction item against it.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
import time
from pathlib import Path

import httpx

from evalclaw.execution.vm_provider import destroy_vm_session
from evalclaw.runners import agent as runner_agent
from evalclaw.runners.agent import run_agent_interaction
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    TargetModelConfig,
    TaskType,
)

SMOKE_DIR = Path(r"D:\localwork\vm_backends\smoke")
IMAGE_URL = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
BASE_IMAGE = SMOKE_DIR / "noble-server-cloudimg-amd64.img"
SEED_DIR = SMOKE_DIR / "seed"
SEED_ISO = SMOKE_DIR / "evalclaw-vm-smoke-seed.iso"
SERIAL_LOG = SMOKE_DIR / "evalclaw-vm-smoke-serial.log"


def run(command: list[str], *, timeout: int = 120) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True, timeout=timeout)


def download_base_image() -> None:
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    if BASE_IMAGE.exists() and BASE_IMAGE.stat().st_size > 100_000_000:
        print(f"Using existing base image: {BASE_IMAGE}", flush=True)
        return
    print(f"Downloading Ubuntu cloud image to {BASE_IMAGE}", flush=True)
    with httpx.stream("GET", IMAGE_URL, follow_redirects=True, timeout=120, trust_env=True) as response:
        response.raise_for_status()
        tmp = BASE_IMAGE.with_suffix(".qcow2.part")
        with tmp.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
        tmp.replace(BASE_IMAGE)


def bridge_server_source() -> str:
    return r'''
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = "/tmp/evalclaw-vm-agent-smoke"
os.makedirs(ROOT, exist_ok=True)
SESSIONS = {}


def read_json(handler):
    length = int(handler.headers.get("Content-Length") or "0")
    if not length:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def send(handler, payload, status=200):
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def safe_path(value):
    raw = str(value or "agent_note.txt").replace("\\", "/").lstrip("/")
    path = os.path.normpath(os.path.join(ROOT, raw))
    if not path.startswith(ROOT):
        raise ValueError("path escapes smoke root")
    return path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/health":
            send(self, {"status": "ok", "observation": "EvalClaw VM smoke bridge is ready."})
            return
        send(self, {"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/sessions":
            payload = read_json(self)
            session_id = "smoke-session"
            SESSIONS[session_id] = payload.get("session") or {}
            send(self, {"session_id": session_id, "observation": "VM session started. Write /agent_note.txt with the requested phrase, then evaluate."})
            return
        if self.path.endswith("/actions"):
            payload = read_json(self)
            action = str(payload.get("action") or "")
            args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            try:
                if action == "write_file":
                    path = safe_path(args.get("path"))
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as file:
                        file.write(str(args.get("content") or ""))
                    send(self, {"observation": f"wrote {os.path.relpath(path, ROOT)}"})
                    return
                if action == "read_file":
                    with open(safe_path(args.get("path")), encoding="utf-8") as file:
                        send(self, {"observation": file.read()})
                    return
                if action == "list_files":
                    send(self, {"observation": "\\n".join(sorted(os.listdir(ROOT)))})
                    return
                send(self, {"observation": f"ignored action {action}"})
            except Exception as exc:
                send(self, {"error": str(exc), "observation": str(exc)}, 400)
            return
        if self.path.endswith("/evaluate"):
            payload = read_json(self)
            evaluation = payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {}
            expected_files = evaluation.get("expected_files")
            if isinstance(expected_files, list) and expected_files:
                checks = []
                for expected in expected_files:
                    if not isinstance(expected, dict):
                        continue
                    expected_path = expected.get("path") or "agent_note.txt"
                    contains = expected.get("contains")
                    if isinstance(contains, str):
                        contains = [contains]
                    if not isinstance(contains, list):
                        contains = [expected.get("expected_text") or ""]
                    try:
                        with open(safe_path(expected_path), encoding="utf-8") as file:
                            content = file.read()
                    except FileNotFoundError:
                        content = ""
                    required_texts = [str(text) for text in contains if str(text)]
                    passed = bool(content) and all(text in content for text in required_texts)
                    checks.append({"path": expected_path, "passed": passed, "required_texts": required_texts})
                passed_count = sum(1 for check in checks if check["passed"])
                score = passed_count / len(checks) if checks else 0.0
                send(self, {"score": score, "done": score >= 1.0, "observation": f"passed_file_checks={passed_count}/{len(checks)}", "checks": checks})
                return
            expected_path = evaluation.get("path") or "agent_note.txt"
            expected_text = evaluation.get("expected_text") or "VM smoke success"
            try:
                with open(safe_path(expected_path), encoding="utf-8") as file:
                    content = file.read()
            except FileNotFoundError:
                content = ""
            passed = expected_text in content
            send(self, {"score": 1.0 if passed else 0.0, "done": passed, "observation": f"expected_text_found={passed}"})
            return
        send(self, {"error": "not found"}, 404)

    def do_DELETE(self):
        send(self, {"deleted": True})


ThreadingHTTPServer(("0.0.0.0", 7766), Handler).serve_forever()
'''


def create_seed_iso() -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    SERIAL_LOG.unlink(missing_ok=True)
    user_data = SEED_DIR / "user-data"
    meta_data = SEED_DIR / "meta-data"
    user_data.write_text(
        "#cloud-config\n"
        "write_files:\n"
        "  - path: /opt/evalclaw-smoke-bridge.py\n"
        "    permissions: '0644'\n"
        "    content: |\n"
        + textwrap.indent(bridge_server_source().strip("\n"), "      ")
        + "\n"
        "  - path: /etc/systemd/system/evalclaw-smoke-bridge.service\n"
        "    permissions: '0644'\n"
        "    content: |\n"
        "      [Unit]\n"
        "      Description=EvaluationClaw VM smoke bridge\n"
        "      After=network.target\n"
        "\n"
        "      [Service]\n"
        "      ExecStart=/usr/bin/python3 /opt/evalclaw-smoke-bridge.py\n"
        "      Restart=always\n"
        "      RestartSec=1\n"
        "      StandardOutput=journal+console\n"
        "      StandardError=journal+console\n"
        "\n"
        "      [Install]\n"
        "      WantedBy=multi-user.target\n"
        "runcmd:\n"
        "  - [systemctl, daemon-reload]\n"
        "  - [systemctl, enable, --now, evalclaw-smoke-bridge.service]\n"
        "  - [systemctl, status, --no-pager, evalclaw-smoke-bridge.service]\n",
        encoding="utf-8",
    )
    meta_data.write_text("instance-id: evalclaw-vm-smoke\nlocal-hostname: evalclaw-vm-smoke\n", encoding="utf-8")
    wsl_seed_dir = "/mnt/d/localwork/vm_backends/smoke/seed"
    wsl_seed_iso = "/mnt/d/localwork/vm_backends/smoke/evalclaw-vm-smoke-seed.iso"
    run(
        [
            "wsl.exe",
            "--",
            "bash",
            "-lc",
            f"genisoimage -output {wsl_seed_iso} -volid cidata -joliet -rock {wsl_seed_dir}/user-data {wsl_seed_dir}/meta-data >/dev/null 2>&1",
        ],
        timeout=60,
    )


def build_item() -> BenchmarkItem:
    return BenchmarkItem(
        id="vm_agent_smoke",
        dimension_id="vm_file_task",
        task_type=TaskType.agent_interaction,
        prompt=(
            "Inside the VM session, create /agent_note.txt containing exactly this phrase: "
            "VM smoke success. Then run the environment evaluation."
        ),
        metadata={
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm_provider_url": "local://qemu",
                "vm": {
                    "disk_image": str(BASE_IMAGE),
                    "seed_iso": str(SEED_ISO),
                    "disk_format": "qcow2",
                    "bridge": {"guest_port": 7766},
                    "memory_mb": 1024,
                    "cpus": 1,
                    "bridge_wait_timeout": 600,
                    "accel": "tcg",
                    "serial_log": str(SERIAL_LOG),
                },
                "session": {"application": "minimal_http_bridge", "task": "write_file"},
                "evaluation": {"path": "agent_note.txt", "expected_text": "VM smoke success"},
                "max_steps": 3,
                "timeout": 20,
            }
        },
        tags=["vm", "agent_interaction", "smoke"],
    )


def print_serial_log_tail(lines: int = 160) -> None:
    if SERIAL_LOG.exists():
        print("\n--- VM serial log tail ---", flush=True)
        print("\n".join(SERIAL_LOG.read_text(errors="replace").splitlines()[-lines:]), flush=True)
    else:
        print(f"\nVM serial log was not created: {SERIAL_LOG}", flush=True)


def main() -> None:
    download_base_image()
    create_seed_iso()
    item = build_item()
    target = TargetModelConfig(provider="mock", model="vm-smoke-agent")
    config = BenchmarkConfig(
        targets=[target],
        vm_provider_url="local://qemu",
        vm_provider_timeout_s=360,
        vm_provider_destroy_on_cleanup=True,
        environment_claw=False,
    )

    scripted_actions = iter(
        [
            {"action": "write_file", "args": {"path": "/agent_note.txt", "content": "VM smoke success"}},
            {"action": "evaluate", "args": {}},
        ]
    )

    def fake_call_target_model(*args, **kwargs):
        try:
            return json.dumps(next(scripted_actions))
        except StopIteration:
            return json.dumps({"action": "final", "args": {"answer": "done"}})

    original = runner_agent.call_target_model
    runner_agent.call_target_model = fake_call_target_model
    started = time.monotonic()
    try:
        raw, score, reasoning = run_agent_interaction(item, target, config)
    except Exception as exc:
        print(f"VM agent smoke failed after {time.monotonic() - started:.1f}s: {exc}", flush=True)
        print_serial_log_tail()
        raise
    finally:
        runner_agent.call_target_model = original
        # Defensive cleanup in case the environment failed before registering cleanup.
        destroy_vm_session("local://qemu", "evalclaw-vm-agent-smoke")

    output = {
        "score": score,
        "reasoning": reasoning,
        "elapsed_s": round(time.monotonic() - started, 1),
        "raw": json.loads(raw),
    }
    out_path = SMOKE_DIR / "vm_agent_smoke_result.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"score": score, "reasoning": reasoning, "result_path": str(out_path)}, ensure_ascii=False, indent=2))
    if score < 1.0:
        print_serial_log_tail()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
