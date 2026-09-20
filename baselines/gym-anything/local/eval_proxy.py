"""Forward proxy TCP traffic across the dedicated Docker network namespace."""
import argparse
import select
import socket
import socketserver


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(self.server.upstream, timeout=15) as upstream:
            upstream.settimeout(None)
            sockets = [self.request, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], 300)
                if not readable:
                    return
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = upstream if source is self.request else self.request
                    destination.sendall(data)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True)
    parser.add_argument("--upstream", required=True)
    args = parser.parse_args()
    listen_host, listen_port = args.listen.rsplit(":", 1)
    upstream_host, upstream_port = args.upstream.rsplit(":", 1)
    with Server((listen_host, int(listen_port)), Relay) as server:
        server.upstream = (upstream_host, int(upstream_port))
        server.serve_forever()
