from pathlib import Path
from unittest import mock

import paramiko
import pytest
import yaml

from gym_anything.runtime.runners.build_base_qcow2_nodocker import get_cloud_init_user_data
from gym_anything.runtime.runners.qemu_native import QemuNativeRunner
from gym_anything.runtime.runners.qemu_ssh import public_key_for_provisioning


@pytest.fixture
def runner():
    instance = QemuNativeRunner.__new__(QemuNativeRunner)
    instance.is_windows = False
    instance._ssh_user = "ga"
    instance._ssh_password = "password123"
    instance.ssh_port = 2222
    instance._process = mock.Mock()
    instance._process.poll.return_value = None
    return instance


@pytest.mark.parametrize("method", ["probe", "command", "sftp", "native_copy"])
def test_linux_auth_failure_never_retries_with_password(runner, method, tmp_path, monkeypatch):
    key = tmp_path / "missing-key"
    monkeypatch.setenv("GYM_ANYTHING_QEMU_SSH_KEY", str(key))
    with mock.patch("paramiko.SSHClient") as client_class, mock.patch("time.sleep"):
        client = client_class.return_value
        client.connect.side_effect = paramiko.AuthenticationException("Rejected key")
        if method == "probe":
            assert runner._test_ssh_auth() is False
        elif method == "command":
            assert runner._ssh_with_paramiko("true", True, 10).returncode != 0
        elif method == "sftp":
            with pytest.raises(paramiko.AuthenticationException):
                runner._sftp_connect()
        else:
            assert runner._scp_to_vm(2222, str(tmp_path / "file"), "/tmp/file") is False
        assert client.connect.call_count > 0
        for call in client.connect.call_args_list:
            assert "password" not in call.kwargs
            assert call.kwargs["key_filename"] == str(key)
            assert call.kwargs["allow_agent"] is False
            assert call.kwargs["look_for_keys"] is False


def test_subprocess_failure_does_not_fall_back_to_password(runner):
    with mock.patch("subprocess.run", side_effect=OSError("ssh unavailable")), mock.patch("paramiko.SSHClient") as client:
        assert runner._run_ssh_cmd(2222, "true").returncode != 0
        client.assert_not_called()


def test_provisioning_uses_matching_private_key_and_disables_passwords(tmp_path, monkeypatch):
    key = tmp_path / "ssh" / "key"
    monkeypatch.setenv("GYM_ANYTHING_QEMU_SSH_KEY", str(key))
    data = yaml.safe_load(get_cloud_init_user_data())
    public = public_key_for_provisioning()
    assert data["users"][0]["ssh_authorized_keys"] == [public]
    assert data["ssh_pwauth"] is False
    assert key.stat().st_mode & 0o777 == 0o600
    config = next(f["content"] for f in data["write_files"] if f["path"].endswith("00-gym-anything.conf"))
    settings = dict(line.split(None, 1) for line in config.splitlines())
    assert settings["AuthenticationMethods"] == "publickey"
    assert settings["PasswordAuthentication"] == "no"
    assert settings["KbdInteractiveAuthentication"] == "no"
    # Repeated provisioning must retain the same identity.
    assert yaml.safe_load(get_cloud_init_user_data())["users"][0]["ssh_authorized_keys"] == [public]


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_management_ports_preserve_official_bindings(runner, tmp_path, arch):
    runner._guest_arch = arch
    runner._accel_type = "tcg"
    runner.resolution = (1920, 1080)
    runner.is_android = False
    runner._fast_io = False
    runner._fast_input_host_port = None
    runner.memory = "2G"
    runner.cpus = 2
    runner.enable_kvm = False
    with mock.patch("gym_anything.runtime.runners.qemu_native._find_aarch64_firmware", return_value=Path("firmware.fd")):
        cmd = runner._build_qemu_cmd(tmp_path / "disk.qcow2", 5901, 2267, tmp_path)
    net = cmd[cmd.index("-netdev") + 1]
    assert net.split("hostfwd=", 1)[1] == "tcp::2267-:22"
    assert cmd[cmd.index("-vnc") + 1] == ":1,password=on"
