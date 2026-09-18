"""SSH credentials shared by Linux QEMU clients and image provisioning."""

import os
import subprocess
from pathlib import Path


SSH_OPTIONS = [
    "-F", "/dev/null",
    "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes",
    "-o", "IdentityAgent=none",
    "-o", "PreferredAuthentications=publickey",
    "-o", "PasswordAuthentication=no",
    "-o", "KbdInteractiveAuthentication=no",
]

SSHD_CONFIG = """PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PermitRootLogin no
UsePAM yes
"""


def ssh_key_path() -> Path:
    return Path(os.environ.get("GYM_ANYTHING_QEMU_SSH_KEY", "~/.ssh/ga_qemu_key")).expanduser()


def public_key_for_provisioning() -> str:
    key = ssh_key_path()
    key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    key.chmod(0o600)
    return subprocess.run(
        ["ssh-keygen", "-y", "-P", "", "-f", str(key)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def ssh_credentials(is_windows: bool, password: str) -> dict:
    if is_windows:
        return {"password": password, "look_for_keys": False, "allow_agent": False}
    return {"key_filename": str(ssh_key_path()), "look_for_keys": False, "allow_agent": False}
