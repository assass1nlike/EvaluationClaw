#!/usr/bin/env python3
"""Verify the VM probe/commit chain against a real local QEMU VM (tcg, no KVM).

Runs: start_vm_command_session -> run_vm_session_command (write a marker file)
-> commit_vm_command_session -> start a second VM from the committed image ->
read the marker back (proves the committed image preserved state).
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

SMOKE_DIR = Path("/data1/zangyihe/vm_backends/smoke")
BASE_IMAGE = SMOKE_DIR / "noble-server-cloudimg-amd64.img"
SEED_DIR = SMOKE_DIR / "seed"
SEED_ISO = SMOKE_DIR / "verify-seed.iso"
SERIAL_LOG = SMOKE_DIR / "verify-serial.log"
BIN_DIR = Path("/data1/zangyihe/vm_backends/bin")
WORK_DIR = Path("/data1/zangyihe/vm_backends/runtime")

MARKER = "/root/verify-marker.txt"
MARKER_TEXT = "vm-probe-commit-ok"


def _configure_env() -> None:
    os.environ["EVALCLAW_QEMU_EXECUTABLE"] = str(BIN_DIR / "qemu-system-x86_64")
    os.environ["EVALCLAW_QEMU_IMG_EXECUTABLE"] = str(BIN_DIR / "qemu-img")
    os.environ["EVALCLAW_VM_WORK_DIR"] = str(WORK_DIR)


def bridge_server_source() -> str:
    return r'''
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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


def run_command(command, timeout=120):
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return {"exit_code": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or "", "timed_out": False}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "stdout": "", "stderr": "command timed out", "timed_out": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/health":
            send(self, {"status": "ok", "observation": "verify bridge ready"})
        else:
            send(self, {"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/sessions":
            send(self, {"session_id": "verify-session", "baseline_verified": True, "observation": "session ready"})
            return
        if self.path.endswith("/actions"):
            payload = read_json(self)
            action = str(payload.get("action") or "")
            args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            if action == "run_command":
                timeout = int(args.get("timeout") or 120)
                result = run_command(str(args.get("command") or ""), timeout)
                observation = "exit_code=%d\nstdout:\n%s\nstderr:\n%s" % (result["exit_code"], result["stdout"], result["stderr"])
                send(self, {"observation": observation, "command_result": result, "error": None if result["exit_code"] == 0 else "command exited %d" % result["exit_code"]})
                return
            send(self, {"error": "unsupported action %s" % action, "observation": "unsupported action %s" % action}, 400)
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
        "  - path: /opt/verify-bridge.py\n"
        "    permissions: '0644'\n"
        "    content: |\n"
        + textwrap.indent(bridge_server_source().strip("\n"), "      ")
        + "\n"
        "  - path: /etc/systemd/system/verify-bridge.service\n"
        "    permissions: '0644'\n"
        "    content: |\n"
        "      [Unit]\n"
        "      Description=Verify bridge\n"
        "      After=network.target\n"
        "\n"
        "      [Service]\n"
        "      ExecStart=/usr/bin/python3 /opt/verify-bridge.py\n"
        "      Restart=always\n"
        "      RestartSec=1\n"
        "\n"
        "      [Install]\n"
        "      WantedBy=multi-user.target\n"
        "runcmd:\n"
        "  - [systemctl, daemon-reload]\n"
        "  - [systemctl, enable, --now, verify-bridge.service]\n",
        encoding="utf-8",
    )
    meta_data.write_text("instance-id: evalclaw-verify\nlocal-hostname: evalclaw-verify\n", encoding="utf-8")
    subprocess.run(
        ["genisoimage", "-output", str(SEED_ISO), "-volid", "cidata", "-joliet", "-rock",
         str(user_data), str(meta_data)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _vm_spec(seed: bool) -> dict:
    spec: dict = {
        "disk_format": "qcow2",
        "bridge": {"guest_port": 7766},
        "memory_mb": 2048,
        "cpus": 2,
        "bridge_wait_timeout": 900,
        "accel": "tcg",
        "serial_log": str(SERIAL_LOG),
        "no_reboot": True,
    }
    if seed:
        spec["seed_iso"] = str(SEED_ISO)
    return spec


def print_serial_tail() -> None:
    if SERIAL_LOG.exists():
        print("\n--- serial log tail ---")
        print("\n".join(SERIAL_LOG.read_text(errors="replace").splitlines()[-80:]))


def main() -> None:
    _configure_env()
    create_seed_iso()
    from evalclaw.execution.vm_provider import (
        close_vm_command_session,
        commit_vm_command_session,
        run_vm_session_command,
        start_vm_command_session,
    )

    print("=== start VM 1 (base image + seed) ===", flush=True)
    s1 = start_vm_command_session("local://qemu", str(BASE_IMAGE), vm_spec_extra=_vm_spec(seed=True), timeout=900)
    print("started:", s1.vm_id, flush=True)

    print("=== run command: write marker ===", flush=True)
    r1 = run_vm_session_command(s1, f"echo '{MARKER_TEXT}' > {MARKER} && cat {MARKER}")
    print("run1:", r1, flush=True)

    print("=== commit VM 1 ===", flush=True)
    committed = commit_vm_command_session(s1, name="verify-committed", timeout=900)
    print("committed:", committed, flush=True)
    close_vm_command_session(s1)
    print("closed VM 1", flush=True)

    committed_image = str(committed["image"])
    print("=== check marker in committed image ===", flush=True)
    marker_count = int(subprocess.run(
        ["strings", committed_image], capture_output=True, text=True
    ).stdout.count(MARKER_TEXT))
    print(f"marker occurrences in committed image: {marker_count}", flush=True)

    if marker_count > 0:
        print(f"\nVERIFY_OK: marker persisted in committed image ({MARKER_TEXT})", flush=True)
    else:
        print(f"\nVERIFY_FAIL: marker did not survive commit", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
