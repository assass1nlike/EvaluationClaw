"""Guest-only relay for software VMs to the generation VM's restricted egress."""
import select
import socket
import socketserver


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(('10.0.2.100', 3128), timeout=20) as remote:
            remote.settimeout(None)
            while True:
                ready, _, _ = select.select([self.request, remote], [], [], 300)
                if not ready:
                    return
                for src in ready:
                    data = src.recv(65536)
                    if not data:
                        return
                    (remote if src is self.request else self.request).sendall(data)


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    Server(('0.0.0.0', 3128), Handler).serve_forever()
