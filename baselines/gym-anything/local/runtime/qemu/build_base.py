"""Build the official shared GNOME image once before parallel workers start."""
import os
from pathlib import Path

root = Path(__file__).resolve().parent
os.environ["PATH"] = str(root / "bin") + os.pathsep + os.environ["PATH"]
os.environ["GYM_ANYTHING_QEMU_CACHE"] = str(root / "secure-cache")
os.environ["GYM_ANYTHING_QEMU_SSH_KEY"] = str(root / "ssh" / "key")

from gym_anything.runtime.runners.qemu_native import QemuNativeRunner
from gym_anything.specs import EnvSpec

runner = QemuNativeRunner(EnvSpec(id="base_image_setup"))
if not runner.base_qcow2.exists():
    runner._create_base_qcow2()
print(runner.base_qcow2)
