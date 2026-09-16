"""Check the official base VM, SSH execution, and desktop screenshot."""
import os
from pathlib import Path

root = Path(__file__).resolve().parent
os.environ["PATH"] = str(root / "bin") + os.pathsep + os.environ["PATH"]
os.environ["GYM_ANYTHING_QEMU_CACHE"] = str(root / "cache")
from gym_anything.runtime.runners.qemu_native import QemuNativeRunner
from gym_anything.specs import EnvSpec

output = root.parents[1] / "outputs" / "qemu_setup"
runner = QemuNativeRunner(EnvSpec.from_dict({"id": "base_image_smoke", "vnc": {"password": "password"}, "recording": {"enable": False, "output_dir": str(output)}}))
assert runner.enable_kvm, "KVM permission missing; run with sg kvm"
try:
    runner.start(seed=42)
    print(runner.exec_capture("cloud-init status --long; command -v gnome-shell; command -v Xvnc; DISPLAY=:1 xdpyinfo | head -5"))
    assert runner.capture_screenshot(output / "desktop.png")
finally:
    runner.stop()
