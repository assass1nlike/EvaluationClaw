from __future__ import annotations

import argparse
import socket
import threading


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
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle(client: socket.socket, target_host: str, target_port: int) -> None:
    with client:
        with socket.create_connection((target_host, target_port), timeout=10) as target:
            left = threading.Thread(target=_pipe, args=(client, target), daemon=True)
            right = threading.Thread(target=_pipe, args=(target, client), daemon=True)
            left.start()
            right.start()
            left.join()
            right.join()


def main() -> None:
    parser = argparse.ArgumentParser(description="Small TCP forwarder for local proxy bridging.")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, required=True)
    args = parser.parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.listen_host, args.listen_port))
        server.listen()
        while True:
            client, _ = server.accept()
            thread = threading.Thread(
                target=_handle,
                args=(client, args.target_host, args.target_port),
                daemon=True,
            )
            thread.start()


if __name__ == "__main__":
    main()
