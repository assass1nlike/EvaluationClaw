from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Thread
import time
import unittest
from unittest.mock import patch

import httpx
from api import start_api
from rate_limit import RateLimit, SharedSlots


class TransportTest(unittest.TestCase):
    def test_multiple_forwarders_share_concurrency_and_actual_send_rate(self):
        active=0
        peak=0
        arrivals=[]
        lock=Lock()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                nonlocal active,peak
                self.rfile.read(int(self.headers['Content-Length']))
                with lock:
                    active+=1;peak=max(peak,active);arrivals.append(time.time())
                time.sleep(0.04)
                content=b'{"choices":[{"message":{"content":"answer"}}]}'
                self.send_response(200);self.send_header('Content-Length',str(len(content)));self.end_headers()
                self.wfile.write(content)
                with lock: active-=1
        provider=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=provider.serve_forever,daemon=True);thread.start()
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'a').mkdir();(root/'b').mkdir()
            upstream=f'http://127.0.0.1:{provider.server_port}/v1'
            target={'base_url':upstream,'api_key':'test','model':'gpt-5.6-sol','extra_body':{},'rpm':5}
            with patch('api.RateLimit',side_effect=lambda path,limit:RateLimit(root/'rpm.json',limit,window=.2)), \
                 patch('api.SharedSlots',side_effect=lambda path,limit:SharedSlots(root/'slots',limit)):
                servers=[start_api(upstream,'key','deepseek-flash',{},42,root/name,test_taker=target,
                                  parallel={'target':3,'judge':3,'target_timeout':10}) for name in ('a','b')]
            try:
                with httpx.Client(timeout=20,trust_env=False) as client:
                    def call(i):
                        response=client.post(servers[i%2][0]+'/chat/completions',json={'model':'gpt-autobencher-target'})
                        self.assertEqual(response.status_code,200)
                    with ThreadPoolExecutor(max_workers=12) as pool:
                        list(pool.map(call,range(24)))
                self.assertGreater(peak,1)
                self.assertLessEqual(peak,3)
                rows=[json.loads(line) for name in ('a','b') for line in (root/name/'requests.jsonl').read_text().splitlines()]
                sent=sorted(r['sent'] for r in rows)
                self.assertEqual(len(sent),24)
                for first,last in zip(sent,sent[5:]):self.assertGreaterEqual(last-first,.2)
            finally:
                for _,close in servers:close()
                provider.shutdown();provider.server_close();thread.join()


if __name__=='__main__':unittest.main()

class ProxyTraceTest(unittest.TestCase):
    def test_proxy_connect_does_not_start_api_quota_clock(self):
        from types import SimpleNamespace
        import requests
        with TemporaryDirectory() as directory:
            root=Path(directory)
            limiter=RateLimit(root/'rpm.json',50)
            def post(*args,**kwargs):
                trace=kwargs['extensions']['trace']
                trace('http11.send_request_headers.started',{'request':SimpleNamespace(method=b'CONNECT')})
                trace('http11.send_request_headers.complete',{'return_value':None})
                self.assertIsNone(json.loads((root/'rpm.json').read_text())[0]['time'])
                trace('http11.send_request_headers.started',{'request':SimpleNamespace(method=b'POST')})
                trace('http11.send_request_headers.complete',{'return_value':None})
                self.assertIsInstance(json.loads((root/'rpm.json').read_text())[0]['time'],float)
                return SimpleNamespace(status_code=200,content=b'{"choices":[{"message":{"content":"answer"}}]}')
            target={'base_url':'https://example.invalid','api_key':'test','model':'gpt-5.6-sol','extra_body':{},'rpm':50}
            with patch('api.RateLimit',return_value=limiter),patch('api.httpx.Client.post',side_effect=post):
                url,close=start_api('https://example.invalid','test','deepseek-flash',{},42,root,test_taker=target)
                try:
                    response=requests.post(url+'/chat/completions',json={'model':'gpt-autobencher-target'},timeout=10)
                    self.assertEqual(response.status_code,200)
                finally:close()
