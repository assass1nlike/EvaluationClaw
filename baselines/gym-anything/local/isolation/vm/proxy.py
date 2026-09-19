"""Public download/API proxy over a Unix socket; never forwards to private IPs."""
import ipaddress
import json
import os
import select
import socket
import socketserver
import threading
import subprocess
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

DOMAINS = ('ubuntu.com', 'debian.org', 'github.com', 'githubusercontent.com',
           'docker.com', 'docker.io', 'pypi.org', 'pythonhosted.org', 'api.deepseek.com',
           'ghcr.io', 'packages.microsoft.com', 'deb.nodesource.com', 'nodejs.org',
           'registry.npmjs.org', 'registry.yarnpkg.com', 'dl.yarnpkg.com',
           'download.moodle.org', 'wordpress.org', 'qgis.org', 'r-project.org',
           'download1.rstudio.org', 'cdn.devlabs.io')
LOCAL_NETWORKS = []


def resolve_public(host, port):
    host = host.lower().rstrip('.')
    if port not in (80, 443) or not any(host == d or host.endswith('.' + d) for d in DOMAINS):
        raise ValueError('destination not permitted')
    addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    parsed = [ipaddress.ip_address(ip) for ip in addresses]
    if not parsed or any(not ip.is_global or ip.is_multicast or
                         any(ip in network for network in LOCAL_NETWORKS) for ip in parsed):
        raise ValueError('nonpublic destination')
    return next((ip for ip in addresses if ':' not in ip), addresses[0])


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def setup(self):
        self.request.settimeout(30)
        super().setup()

    def log_message(self, fmt, *args):
        pass  # URLs/headers can contain credentials.

    def do_CONNECT(self):
        self.forward(True)

    def do_GET(self):
        self.forward(False)

    do_HEAD = do_GET

    def forward(self, tunnel):
        remote = None
        host, port = None, None
        try:
            target = urlsplit(('https://' if tunnel else '') + self.path)
            host, port = target.hostname, target.port or (443 if tunnel else 80)
            if target.username or target.password or not host or (not tunnel and target.scheme != 'http'):
                raise ValueError('invalid destination')
            ip = resolve_public(host, port)
        except (ValueError, OSError):
            if self.server.audit:
                with open(self.server.audit, 'a') as log:
                    log.write(json.dumps({'event': 'denied', 'host': host, 'port': port}) + '\n')
            self.send_error(403, 'Destination denied')
            return
        try:
            # Pin the resolved public IP even when using the local upstream proxy.
            remote = socket.create_connection(
                ('127.0.0.1', int(os.environ.get('GYM_VM_UPSTREAM_PROXY_PORT', '7890'))), timeout=20)
            authority = f'[{ip}]:{port}' if ':' in ip else f'{ip}:{port}'
            remote.sendall(f'CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n'.encode())
            head = bytearray()
            while not head.endswith(b'\r\n\r\n') and len(head) < 8192:
                data = remote.recv(1)
                if not data:
                    raise OSError('upstream closed')
                head.extend(data)
            if head.split(b' ', 2)[1] != b'200':
                raise OSError('upstream denied')
            if tunnel:
                self.send_response(200, 'Connection established')
                self.end_headers()
            else:
                path = target.path or '/'
                if target.query:
                    path += '?' + target.query
                request = f'{self.command} {path} HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n'
                for name, value in self.headers.items():
                    if name.lower() not in ('host', 'connection', 'proxy-connection', 'proxy-authorization'):
                        request += f'{name}: {value}\r\n'
                remote.sendall((request + '\r\n').encode('latin1'))
            remote.settimeout(30)
            while True:
                ready, _, _ = select.select([self.connection, remote], [], [], 120)
                if not ready:
                    break
                for src in ready:
                    data = src.recv(65536)
                    if not data:
                        return
                    (remote if src is self.connection else self.connection).sendall(data)
        except OSError:
            return
        finally:
            if remote:
                remote.close()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, path, audit=None):
        global LOCAL_NETWORKS
        interfaces = json.loads(subprocess.check_output(['ip', '-j', 'address', 'show'], text=True))
        LOCAL_NETWORKS = [ipaddress.ip_network(f"{addr['local']}/{addr['prefixlen']}", strict=False)
                          for interface in interfaces for addr in interface['addr_info']]
        self.slots = threading.BoundedSemaphore(32)
        self.audit = audit
        super().__init__(path, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()
