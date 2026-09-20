"""Prepare and verify a separate evaluation base with a guest Docker proxy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "local/runtime/qemu/evaluation-cache"
SOURCE = ROOT / "local/runtime/qemu/secure-cache/base_ubuntu_gnome.qcow2"
PROXY = "http://10.0.2.2:17891"
DROPIN = ('[Service]\nEnvironment="HTTP_PROXY=' + PROXY + '"\n'
          'Environment="HTTPS_PROXY=' + PROXY + '"\n'
          'Environment="NO_PROXY=localhost,127.0.0.1,::1"\n')


def prepare():
    from gym_anything.runtime.runners.qemu_ssh import SSHD_CONFIG
    disk = OUTPUT / "provision.qcow2"
    subprocess.run([str(ROOT / "local/runtime/qemu/bin/qemu-img"), "create", "-f", "qcow2", "-F", "qcow2",
                    "-b", str(SOURCE), str(disk)], check=True)
    config = {
        "ssh_pwauth": False,
        "write_files": [
            {"path": "/etc/systemd/system/docker.service.d/10-gym-proxy.conf",
             "permissions": "0644", "content": DROPIN},
            {"path": "/etc/ssh/sshd_config.d/00-gym-anything.conf",
             "permissions": "0600", "content": SSHD_CONFIG},
        ],
        "runcmd": [["/usr/sbin/sshd", "-t"],
                   ["sh", "-c", "echo GYM_EVAL_PROXY_CONFIGURED > /dev/ttyS0"]],
        "power_state": {"mode": "poweroff", "delay": "now", "timeout": 30, "condition": True},
    }
    (OUTPUT / "user-data").write_text("#cloud-config\n" + yaml.safe_dump(config))
    (OUTPUT / "meta-data").write_text("instance-id: gym-eval-proxy-20260920\n")
    subprocess.run(["genisoimage", "-output", str(OUTPUT / "seed.iso"), "-volid", "cidata",
                    "-joliet", "-rock", str(OUTPUT / "user-data"), str(OUTPUT / "meta-data")],
                   check=True, capture_output=True)


def worker():
    os.environ.update(
        GYM_ANYTHING_QEMU_CACHE=str(OUTPUT),
        GYM_ANYTHING_QEMU_SSH_KEY=str(ROOT / "local/runtime/qemu/ssh/key"),
        GYM_ANYTHING_QEMU_WORK_DIR=str(ROOT / "local/q/eval-network-check"),
    )
    random.seed(42)
    disk = OUTPUT / "provision.qcow2"
    with (OUTPUT / "provision.log").open("w") as log:
        proc = subprocess.Popen([
            "qemu-system-x86_64", "-enable-kvm", "-cpu", "host", "-m", "3072", "-smp", "2",
            "-drive", f"file={disk},format=qcow2,if=virtio", "-cdrom", str(OUTPUT / "seed.iso"),
            "-nic", "none", "-display", "none", "-monitor", "none", "-serial", "stdio", "-no-reboot",
        ], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            if proc.wait(timeout=600) != 0:
                raise RuntimeError("Base provisioning failed")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    if "GYM_EVAL_PROXY_CONFIGURED" not in (OUTPUT / "provision.log").read_text().splitlines():
        raise RuntimeError("Base provisioning did not finish")
    base = OUTPUT / "base_ubuntu_gnome.qcow2"
    subprocess.run(["qemu-img", "convert", "-O", "qcow2", str(disk), str(base)], check=True)
    verify()


def verify():
    os.environ.update(
        GYM_ANYTHING_QEMU_CACHE=str(OUTPUT),
        GYM_ANYTHING_QEMU_SSH_KEY=str(ROOT / "local/runtime/qemu/ssh/key"),
        GYM_ANYTHING_QEMU_WORK_DIR=str(ROOT / "local/q/eval-network-check"),
    )
    random.seed(42)
    base = OUTPUT / "base_ubuntu_gnome.qcow2"
    from gym_anything.runtime.runners.qemu_native import QemuNativeRunner
    from gym_anything.specs import EnvSpec
    runner = QemuNativeRunner(EnvSpec.from_dict({
        "id": "eval_network_check", "resources": {"cpu": 2, "mem_gb": 3, "net": True},
        "vnc": {"password": "password"}, "recording": {"enable": False},
    }))
    try:
        runner.start(seed=42)
        def guest(command, timeout=60):
            result = runner._run_ssh_cmd(runner.ssh_port, command, timeout=timeout)
            if result.returncode:
                raise RuntimeError(f"Guest check failed: {result.stderr.decode(errors='replace')}")
            return result.stdout.decode().replace("\r\n", "\n")
        ssh = guest("sudo /usr/sbin/sshd -T -C user=ga,host=localhost,addr=10.0.2.2")
        settings = dict(line.split(None, 1) for line in ssh.splitlines())
        assert settings["passwordauthentication"] == "no"
        assert settings["authenticationmethods"] == "publickey"
        assert guest("cat /etc/systemd/system/docker.service.d/10-gym-proxy.conf") == DROPIN
        registry = guest(f"curl --proxy {PROXY} --max-time 30 -sS -o /dev/null -w '%{{http_code}}' https://registry-1.docker.io/v2/")
        assert registry.strip() == "401", registry
        install = guest("sudo apt-get update -qq && sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io", 600)
        (OUTPUT / "verify-install.log").write_text(install)
        pull = guest("sudo docker pull postgres:11", 600)
        (OUTPUT / "verify-pull.log").write_text(pull)
        digest = guest("sudo docker image inspect postgres:11 --format '{{json .RepoDigests}}'")
        evidence = dict(seed=42, proxy=PROXY, registry_status=registry.strip(),
                        docker_root=subprocess.check_output(["docker", "info", "--format", "{{.DockerRootDir}}"], text=True).strip(),
                        ssh_authentication=settings["authenticationmethods"],
                        passwordauthentication=settings["passwordauthentication"],
                        pulled_image=json.loads(digest),
                        source_sha256=hashlib.file_digest(SOURCE.open("rb"), "sha256").hexdigest(),
                        base_sha256=hashlib.file_digest(base.open("rb"), "sha256").hexdigest())
        (OUTPUT / "verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    finally:
        runner.stop()
    (OUTPUT / "READY").write_text("Guest Docker proxy and public-key-only SSH verified.\n")
    (OUTPUT / "provision.qcow2").unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--verify", action="store_true", help="Verify an already prepared base")
    args = parser.parse_args()
    if args.worker:
        verify() if args.verify else worker()
    else:
        from local.eval_docker import use_dedicated_docker
        use_dedicated_docker()
        if not args.verify:
            OUTPUT.mkdir(mode=0o700, exist_ok=False)
            (OUTPUT / "workspace").mkdir()
            (OUTPUT / "config.json").write_text(json.dumps({"env": "eval-network-check", "runner": "qemu"}))
            prepare()
        from seed_batch import runtime_command
        environ = dict(os.environ, PYTHONPATH=f"{ROOT / 'src'}:{ROOT}", PYTHONHASHSEED="42",
                       PATH=f"{ROOT / 'local/runtime/qemu/bin'}:{ROOT / '.venv/bin'}:/usr/local/bin:/usr/bin:/bin")
        command = runtime_command(OUTPUT, [str(ROOT / ".venv/bin/python"), __file__, "--worker",
                                          *(["--verify"] if args.verify else [])], environ)
        raise SystemExit(subprocess.run(command, env=environ).returncode)
