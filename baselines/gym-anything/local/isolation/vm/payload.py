"""Copy pinned framework code and installed dependencies into a guest-only bundle."""
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'local/outputs/vm_isolation_check'
UPSTREAM = ROOT/'local/outputs/upstream'
COMMIT = '774476d752d748a69288f2ead97f75dd9df08ddb'
BUNDLE = OUT/'framework.tar'
OUT.mkdir(parents=True, exist_ok=True)
subprocess.run(['git','-C',str(UPSTREAM),'archive',COMMIT,
                '--prefix='+str(ROOT).lstrip('/')+'/', '-o',str(BUNDLE),
                'src','extras/research/task_generation/propose_and_amplify',
                'benchmarks/cua_world/environments/libreoffice_writer_env'],check=True)
with tarfile.open(BUNDLE,'a') as tar:
    for rel in ['src/gym_anything/runtime/runners/docker.py',
                'src/gym_anything/runtime/runners/qemu_apptainer.py',
                'src/gym_anything/runtime/runners/qemu_native.py',
                'src/gym_anything/runtime/runners/qemu_ssh.py',
                'src/gym_anything/runtime/runners/build_base_qcow2_nodocker.py',
                'extras/research/task_generation/propose_and_amplify/pipeline/propose_cc.py',
                'local/generate.py', '.venv']:
        tar.add(ROOT/rel,arcname=str(ROOT/rel).lstrip('/'))
    python_home=(ROOT/'.venv/bin/python').resolve().parent.parent
    tar.add(python_home,arcname=str(python_home).lstrip('/'))
    cli=ROOT/'local/runtime/tools/claude'
    tar.add(cli,arcname='home/ga/.local/bin/claude')
print(BUNDLE)
