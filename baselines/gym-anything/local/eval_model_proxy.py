"""Forward unchanged API requests through two independently rate-limited keys."""
import argparse
from collections import deque
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlsplit


class KeyPool:
    def __init__(self, count, rpm=50, clock=time.monotonic):
        self.history = [deque() for _ in range(count)]
        self.rpm, self.clock = rpm, clock
        self.condition = threading.Condition()

    def reserve(self, now):
        """Called under the lock; return a key or the delay before checking again."""
        ready = []
        for history in self.history:
            while history and now - history[0] >= 60.01:
                history.popleft()
            spacing = history[-1] + 60 / self.rpm + 0.01 if history else now
            window = history[0] + 60.01 if len(history) >= self.rpm else now
            ready.append(max(spacing, window))
        index = min(range(len(ready)), key=lambda i: ready[i])
        if ready[index] <= now:
            self.history[index].append(now)
            return index, 0
        return None, ready[index] - now

    def acquire(self):
        with self.condition:
            while True:
                index, delay = self.reserve(self.clock())
                if index is not None:
                    return index
                self.condition.wait(timeout=delay)


HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'authorization', 'x-api-key'}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass  # Do not log request headers, bodies, or credentials.

    def respond(self, status, message):
        payload = json.dumps(message).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == '/health':
            return self.respond(200, {'ready': True, 'keys': len(self.server.keys), 'rpm_per_key': self.server.pool.rpm})
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        provided = self.headers.get('x-api-key') or self.headers.get('Authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(provided, self.server.token):
            return self.respond(401, {'error': 'Invalid local gateway credential'})
        if not self.path.startswith('/v1/'):
            return self.respond(404, {'error': 'Unsupported API path'})
        if self.headers.get('Transfer-Encoding'):
            return self.respond(411, {'error': 'Content-Length required'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0:
                raise ValueError()
        except ValueError:
            return self.respond(400, {'error': 'Invalid Content-Length'})
        connection, sent_headers = None, False
        event = dict(received=time.time(), path=self.path, request_bytes=length)
        try:
            # Spool image-heavy requests to disk while waiting, instead of retaining them in RAM.
            with tempfile.TemporaryFile(dir=self.server.spool) as body:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ConnectionError('Client disconnected during request upload')
                    body.write(chunk)
                    remaining -= len(chunk)
                body.seek(0)
                started = time.monotonic()
                index = self.server.pool.acquire()
                event.update(key_index=index + 1, dispatched=time.time(), queue_seconds=time.monotonic() - started)
                key = self.server.keys[index]
                headers = {name: value for name, value in self.headers.items()
                           if name.lower() not in HOP_HEADERS | {'content-length'}}
                headers.update({'Authorization': 'Bearer ' + key, 'x-api-key': key,
                                'Host': self.server.upstream.netloc, 'Content-Length': str(length)})
                target = self.server.upstream
                if self.server.proxy:
                    proxy = self.server.proxy
                    connection = http.client.HTTPSConnection(proxy.hostname, proxy.port, timeout=600)
                    connection.set_tunnel(target.hostname, target.port or 443)
                else:
                    connection = http.client.HTTPSConnection(target.hostname, target.port or 443, timeout=600)
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                event['status'] = response.status
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() not in HOP_HEADERS:
                        self.send_header(name, value)
                self.send_header('Connection', 'close')
                self.end_headers()
                sent_headers = True
                self.close_connection = True
                total = 0
                while chunk := response.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    total += len(chunk)
                event['response_bytes'] = total
        except (OSError, http.client.HTTPException) as error:
            event['error'] = type(error).__name__
            if not sent_headers:
                try:
                    self.respond(502, {'error': 'Upstream transport failed'})
                except OSError:
                    pass
        finally:
            if connection:
                connection.close()
            event['finished'] = time.time()
            with self.server.log_lock, self.server.log_path.open('a') as log:
                log.write(json.dumps(event) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secrets', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18962)
    parser.add_argument('--upstream', default='https://api.sudorelay.com')
    parser.add_argument('--proxy', default='')
    args = parser.parse_args()
    secrets = json.loads(args.secrets.read_text())
    args.state.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    server.keys, server.token = secrets['keys'], secrets['token']
    server.pool = KeyPool(len(server.keys), rpm=50)
    server.spool = args.state
    server.log_path, server.log_lock = args.state / 'requests.jsonl', threading.Lock()
    server.upstream = urlsplit(args.upstream)
    server.proxy = urlsplit(args.proxy) if args.proxy else None
    server.serve_forever()


if __name__ == '__main__':
    main()
