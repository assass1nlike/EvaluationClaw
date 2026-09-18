"""Local OpenAI-compatible forwarding and request recording."""

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import httpx


def start_api(base_url, api_key, model, extra_body, seed, run_dir):
    client = httpx.Client(timeout=300)
    records = (run_dir / "requests.jsonl").open("a")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body.update(extra_body)
            body.update(model=model, seed=seed)
            started = time.time()
            try:
                response = client.post(
                    base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
                status, content = response.status_code, response.content
            except httpx.HTTPError as error:
                status = 502
                content = json.dumps({"error": {"message": str(error)}}).encode()
            try:
                payload = json.loads(content)
            except ValueError:
                payload = content.decode(errors="replace")
            records.write(json.dumps({
                "started": started, "seconds": time.time() - started,
                "request": body, "status": status, "response": payload,
            }, ensure_ascii=False) + "\n")
            records.flush()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def close():
        server.shutdown()
        thread.join()
        server.server_close()
        client.close()
        records.close()

    return f"http://127.0.0.1:{server.server_port}/v1", close
