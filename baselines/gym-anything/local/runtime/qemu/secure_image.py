"""Prepare a separate key-only base; --run boots temporary verification VMs."""

import argparse
import json
import os
from pathlib import Path
import random
import socket
import subprocess

import paramiko
import yaml

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "secure-cache"
KEY = ROOT / "ssh" / "key"
os.environ["PATH"] = str(ROOT / "bin") + os.pathsep + os.environ["PATH"]
os.environ["GYM_ANYTHING_QEMU_CACHE"] = str(CACHE)
os.environ["GYM_ANYTHING_QEMU_SSH_KEY"] = str(KEY)

from gym_anything.runtime.runners.qemu_ssh import SSHD_CONFIG, public_key_for_provisioning


def prepare():
    CACHE.mkdir(mode=0o700, exist_ok=True)
    public = public_key_for_provisioning()
    source = ROOT / "cache" / "base_ubuntu_gnome.qcow2"
    disk = CACHE / "provision.qcow2"
    if not disk.exists():
        subprocess.run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                        "-b", str(source), str(disk)], check=True, capture_output=True)
    config = {
        "ssh_pwauth": False,
        "write_files": [
            {"path": "/etc/ssh/sshd_config.d/00-gym-anything.conf", "permissions": "0600", "content": SSHD_CONFIG},
            {"path": "/home/ga/.ssh/authorized_keys", "owner": "ga:ga", "permissions": "0600", "content": public + "\n"},
        ],
        "runcmd": [
            ["chmod", "700", "/home/ga/.ssh"],
            ["/usr/sbin/sshd", "-t"],
            ["systemctl", "restart", "ssh"],
            ["python3", "-c",
             "import subprocess; from pathlib import Path; "
             "s = dict(line.split(None, 1) for line in subprocess.check_output("
             "['/usr/sbin/sshd', '-T', '-C', 'user=ga,host=localhost,addr=10.0.2.2'], text=True).splitlines()); "
             "assert s['passwordauthentication'] == 'no'; "
             "assert s['kbdinteractiveauthentication'] == 'no'; "
             "assert s['authenticationmethods'] == 'publickey'; "
             "assert s['pubkeyauthentication'] == 'yes'; "
             "assert s['permitrootlogin'] == 'no'; "
             f"assert Path('/home/ga/.ssh/authorized_keys').read_text().strip() == {public!r}; "
             "Path('/dev/ttyS0').write_text('GYM_SSH_KEYONLY_VERIFIED\\n')"],
        ],
        "power_state": {"mode": "poweroff", "delay": "now", "timeout": 30, "condition": True},
    }
    (CACHE / "user-data").write_text("#cloud-config\n" + yaml.safe_dump(config))
    (CACHE / "meta-data").write_text("instance-id: gym-keyonly-20260918\nlocal-hostname: gym-anything\n")
    subprocess.run(["genisoimage", "-output", str(CACHE / "seed.iso"), "-volid", "cidata",
                    "-joliet", "-rock", str(CACHE / "user-data"), str(CACHE / "meta-data")],
                   check=True, capture_output=True)
    print("Prepared key, copy-on-write disk and cloud-init ISO; no VM started.")


def configure():
    # No NIC, shared filesystem, host mounts, VNC, monitor or forwarded ports.
    cmd = ["qemu-system-x86_64", "-enable-kvm", "-cpu", "host", "-m", "3072", "-smp", "2",
           "-drive", f"file={CACHE / 'provision.qcow2'},format=qcow2,if=virtio",
           "-cdrom", str(CACHE / "seed.iso"), "-nic", "none", "-display", "none",
           "-monitor", "none", "-serial", "stdio", "-no-reboot"]
    with (CACHE / "provision.log").open("w") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            if proc.wait(timeout=600) != 0:
                raise RuntimeError("VM configuration failed; see provision.log")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    if "GYM_SSH_KEYONLY_VERIFIED" not in (CACHE / "provision.log").read_text(errors="replace").splitlines():
        raise RuntimeError("Offline SSH policy verification failed; no networked VM will be started")
    subprocess.run(["qemu-img", "convert", "-O", "qcow2", str(CACHE / "provision.qcow2"),
                    str(CACHE / "base_ubuntu_gnome.qcow2")], check=True)


def verify():
    from gym_anything.runtime.runners.qemu_native import QemuNativeRunner
    from gym_anything.specs import EnvSpec

    runner = QemuNativeRunner(EnvSpec.from_dict({
        "id": "ssh_security_check", "resources": {"net": False, "cpu": 2, "mem_gb": 3},
        "vnc": {"password": "password"},
        "recording": {"enable": False},
    }))
    if not runner.enable_kvm:
        raise RuntimeError("KVM permission required; run with sg kvm")
    try:
        runner.start(seed=42)
        assert runner._test_ssh_auth(), "Key authentication failed"
        result = runner._run_ssh_cmd(runner.ssh_port, "sudo /usr/sbin/sshd -T -C user=ga,host=localhost,addr=10.0.2.2")
        assert result.returncode == 0
        settings = dict(line.split(None, 1) for line in result.stdout.decode().splitlines() if " " in line)
        for k, v in {"passwordauthentication": "no", "kbdinteractiveauthentication": "no",
                     "authenticationmethods": "publickey", "pubkeyauthentication": "yes",
                     "permitrootlogin": "no"}.items():
            assert settings[k] == v, (k, settings.get(k))
        with socket.create_connection(("127.0.0.1", runner.ssh_port), timeout=10) as sock:
            transport = paramiko.Transport(sock)
            try:
                transport.start_client(timeout=10)
                try:
                    transport.auth_none("ga")
                except paramiko.BadAuthenticationType as error:
                    methods = error.allowed_types
                else:
                    raise AssertionError("Unauthenticated SSH accepted")
                assert methods == ["publickey"], methods
                try:
                    transport.auth_password("ga", "password123", fallback=False)
                except paramiko.AuthenticationException:
                    pass
                else:
                    raise AssertionError("Password authentication accepted")
            finally:
                transport.close()
        test_file = CACHE / "transfer.txt"
        test_file.write_text("qemu key-only transfer\n")
        assert runner._scp_to_vm(runner.ssh_port, str(test_file), "/tmp/ssh-check.txt")
        runner.copy_from("/tmp/ssh-check.txt", str(CACHE / "transfer-return.txt"))
        assert (CACHE / "transfer-return.txt").read_bytes() == test_file.read_bytes()
        assert runner.capture_screenshot(CACHE / "desktop.png")
        listeners = subprocess.run(["ss", "-ltnp"], check=True, capture_output=True, text=True).stdout
        relevant = []
        for port in [runner.ssh_port, runner.vnc_port]:
            rows = [line for line in listeners.splitlines()[1:] if line.split()[3].rsplit(":", 1)[-1] == str(port)]
            assert rows and all(line.split()[3].rsplit(":", 1)[0] in ("0.0.0.0", "[::]", "*") for line in rows), rows
            relevant.extend(rows)
        (CACHE / "verification.json").write_text(json.dumps({
            "auth_methods": methods, "password_rejected": True, "ssh_settings": settings,
            "file_transfer": True, "screenshot": True, "listeners": relevant,
            "network": "QEMU user networking restrict=on; official management bindings", "seed": 42,
        }, indent=2) + "\n")
    finally:
        runner.stop()
    (CACHE / "READY").write_text("Key-only SSH and official management bindings verified.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Boot temporary configuration and verification VMs")
    mode.add_argument("--verify", action="store_true", help="Verify the separately configured image")
    args = parser.parse_args()
    random.seed(42)
    if args.run and (CACHE / "base_ubuntu_gnome.qcow2").exists():
        raise SystemExit("Secure image already exists; preserve it and its verification record.")
    if not args.verify:
        prepare()
    if args.run:
        configure()
    if args.run or args.verify:
        if "GYM_SSH_KEYONLY_VERIFIED" not in (CACHE / "provision.log").read_text(errors="replace").splitlines():
            raise SystemExit("Offline SSH policy verification is required before connecting the VM")
        verify()
