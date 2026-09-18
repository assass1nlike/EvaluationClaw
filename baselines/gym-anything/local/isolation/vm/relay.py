"""Connect QEMU guest forwarding or administrator SSH to a fixed local socket."""
import os
import select
import socket
import sys

if sys.argv[1] == 'proxy':
    sock = socket.socket(socket.AF_UNIX)
    sock.connect('/egress/proxy.sock')
else:
    sock = socket.create_connection(('127.0.0.1', 2222), timeout=15)
sock.settimeout(None)
while True:
    ready, _, _ = select.select([0, sock], [], [])
    for src in ready:
        data = os.read(0, 65536) if src == 0 else sock.recv(65536)
        if not data:
            sys.exit(0)
        if src == 0:
            sock.sendall(data)
        else:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
