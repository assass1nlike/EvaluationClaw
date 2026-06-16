"""Small TCP forwarder for local development utilities."""
from __future__ import annotations

import argparse
import socket
import threading


def _close(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        _close(src)
        _close(dst)


def _handle(client: socket.socket, target_host: str, target_port: int) -> None:
    try:
        upstream = socket.create_connection((target_host, target_port), timeout=10)
    except OSError:
        _close(client)
        return
    threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=_pipe, args=(upstream, client), daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Forward TCP connections to another host:port.")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, required=True)
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen(128)
    print(
        f"Forwarding {args.listen_host}:{args.listen_port} "
        f"to {args.target_host}:{args.target_port}",
        flush=True,
    )
    while True:
        client, _ = server.accept()
        threading.Thread(
            target=_handle,
            args=(client, args.target_host, args.target_port),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()
