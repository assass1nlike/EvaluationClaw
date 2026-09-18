"""Run only in the nonprivileged QEMU container; no host writes or stress tests."""
import errno
import json
import os
from pathlib import Path
import socket
import tempfile

result = {}
for label, path in [('root_readonly', '/write-probe'), ('cgroup_readonly', '/sys/fs/cgroup/pids.max')]:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
    except OSError as error:
        assert error.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
        result[label] = error.errno
    else:
        raise AssertionError(label)
assert not Path('/var/run/docker.sock').exists()
assert not Path('/dev/nvme0n1').exists()
try:
    socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
except PermissionError:
    result['raw_socket_denied'] = True
else:
    raise AssertionError('raw socket permitted')
with tempfile.TemporaryFile(dir='/tmp') as f:
    try:
        os.ftruncate(f.fileno(), 50 * 1024**3 + 1)
    except OSError as error:
        assert error.errno == errno.EFBIG
        result['file_size_hard_limit'] = True
    else:
        raise AssertionError('file size limit not enforced')
status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert int(status['CapEff'].strip(), 16) == 0 and status['NoNewPrivs'].strip() == '1'
result.update(capabilities=0, no_new_privileges=True, seccomp=status['Seccomp'].strip())
print(json.dumps(result))
