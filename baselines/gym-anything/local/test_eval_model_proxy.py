from collections import defaultdict
import http.client
from http.server import ThreadingHTTPServer
import io
import json
import threading

from local import eval_model_proxy as proxy


def test_each_key_obeys_rolling_minute_limit():
    pool = proxy.KeyPool(2, rpm=50)
    now, dispatched = 0.0, defaultdict(list)
    while sum(map(len, dispatched.values())) < 240:
        key, delay = pool.reserve(now)
        if key is None:
            now += delay + 1e-8
        else:
            dispatched[key].append(now)
    assert set(dispatched) == {0, 1}
    for events in dispatched.values():
        assert len(events) == 120
        assert events[49] < 60
        assert all(sum(t - 60 < previous <= t for previous in events) <= 50 for t in events)


def test_reservation_is_shared_across_concurrent_requests():
    pool = proxy.KeyPool(2, rpm=50, clock=lambda: 0)
    admitted = []
    def reserve():
        with pool.condition:
            admitted.append(pool.reserve(0)[0])
    threads = [threading.Thread(target=reserve) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(k for k in admitted if k is not None) == [0, 1]


def test_proxy_preserves_body_stream_and_keeps_credentials_private(tmp_path, monkeypatch):
    payload = b'{"model":"gpt-5.6-sol","messages":[{"role":"user","content":"private prompt"}]}'
    sse = b'event: message_start\ndata: {"type":"message_start"}\n\nevent: message_stop\ndata: {}\n\n'
    calls = []

    class Response(io.BytesIO):
        status = 200
        def getheaders(self):
            return [('Content-Type', 'text/event-stream'), ('Transfer-Encoding', 'chunked')]

    class Upstream:
        def __init__(self, *a, **k):
            pass
        def request(self, method, path, body, headers):
            calls.append((method, path, body.read(), headers))
        def getresponse(self):
            return Response(sse)
        def close(self):
            pass

    monkeypatch.setattr(proxy.http.client, 'HTTPSConnection', Upstream)
    server = ThreadingHTTPServer(('127.0.0.1', 0), proxy.Handler)
    server.keys, server.token = ['upstream-secret-1', 'upstream-secret-2'], 'local-secret'
    server.pool = proxy.KeyPool(2)
    server.spool, server.log_path = tmp_path, tmp_path/'requests.jsonl'
    server.log_lock = threading.Lock()
    server.upstream, server.proxy = proxy.urlsplit('https://example.test'), None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=3)
        client.request('POST', '/v1/messages?beta=true', payload,
                       headers={'x-api-key': 'local-secret', 'content-length': str(len(payload))})
        response = client.getresponse()
        assert response.status == 200 and response.read() == sse
        assert response.getheader('Transfer-Encoding') is None
        client.close()
        client = http.client.HTTPConnection(*server.server_address, timeout=3)
        client.request('POST', '/v1/messages', payload, headers={'x-api-key': 'incorrect'})
        assert client.getresponse().status == 401
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(calls) == 1 and calls[0][:3] == ('POST', '/v1/messages?beta=true', payload)
    assert calls[0][3]['x-api-key'] == 'upstream-secret-1'
    assert sum(k.lower() == 'content-length' for k in calls[0][3]) == 1
    event = json.loads(server.log_path.read_text())
    assert event['key_index'] == 1 and event['request_bytes'] == len(payload)
    assert set(event) == {'received', 'path', 'request_bytes', 'key_index', 'dispatched',
                          'queue_seconds', 'status', 'response_bytes', 'finished'}
