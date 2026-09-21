"""Local, source-blind pairwise task review with durable decisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ._katex_assets import inject_katex
from .human_judge_template import HTML


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Artifact(Record):
    label: str = Field(min_length=1)
    path: str = Field(min_length=1)


class Section(Record):
    title: str = Field(min_length=1)
    content: JsonValue


class Candidate(Record):
    source: str = Field(min_length=1)
    task: JsonValue
    response: JsonValue
    sections: list[Section] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)


class Pair(Record):
    id: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    candidates: list[Candidate] = Field(min_length=2, max_length=2)


class ReviewData(Record):
    title: str = "题目质量比较"
    pairs: list[Pair] = Field(min_length=1)


class Decision(Record):
    pair: int = Field(ge=0)
    choice: Literal["A", "B"]
    reason: str = ""


def now():
    return datetime.now(timezone.utc).isoformat()


class ReviewStore:
    def __init__(self, data_path: Path, database: Path, seed: int = 42):
        self.root = data_path.resolve().parent
        self.data = ReviewData.model_validate_json(data_path.read_text(encoding="utf-8"))
        ids = [pair.id for pair in self.data.pairs]
        if len(ids) != len(set(ids)):
            raise ValueError("Pair ids must be unique")
        digest = hashlib.sha256(self.data.model_dump_json().encode())
        self.files = {}
        for i, pair in enumerate(self.data.pairs):
            for j, candidate in enumerate(pair.candidates):
                if candidate.task is None or candidate.task == "" or candidate.task == {}:
                    raise ValueError(f"Pair {pair.id}: task content is required")
                for k, artifact in enumerate(candidate.artifacts):
                    path = (self.root / artifact.path).resolve()
                    if not path.is_relative_to(self.root) or not path.is_file():
                        raise ValueError(f"Pair {pair.id}: artifact must be a file inside the data directory")
                    with path.open("rb") as handle:
                        file_hash = hashlib.sha256()
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            file_hash.update(chunk)
                        digest.update(file_hash.digest())
                    self.files[i, j, k] = path
        self.fingerprint = digest.hexdigest()
        self.seed = seed
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS votes (
                    revision INTEGER PRIMARY KEY, session TEXT NOT NULL, pair INTEGER NOT NULL,
                    choice TEXT NOT NULL CHECK(choice IN ('A','B')), reason TEXT NOT NULL,
                    submitted_at TEXT NOT NULL);
            """)
            expected = {"dataset_sha256": self.fingerprint, "seed": str(seed)}
            existing = dict(db.execute("SELECT key, value FROM meta"))
            if existing and existing != expected:
                raise ValueError("Data or seed changed: use a new database for a new review batch")
            db.executemany("INSERT OR IGNORE INTO meta VALUES (?, ?)", expected.items())

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def new_session(self):
        token = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?)", (token, now()))
        return token

    def check_session(self, token):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM sessions WHERE id=?", (token,)).fetchone():
                raise PermissionError("评审恢复码无效")

    def rank(self, token, purpose, index):
        return hashlib.sha256(json.dumps(
            [self.seed, self.fingerprint, token, purpose, index], separators=(",", ":")
        ).encode()).digest()

    def order(self, token, index):
        self.check_session(token)
        if not 0 <= index < len(self.data.pairs):
            raise ValueError("Unknown pair")
        return [0, 1] if self.rank(token, "side", index)[0] % 2 == 0 else [1, 0]

    def latest(self, token):
        with self.connect() as db:
            rows = db.execute("""SELECT pair, choice, reason, submitted_at, revision FROM votes
                WHERE revision IN (SELECT MAX(revision) FROM votes WHERE session=? GROUP BY pair)
                ORDER BY pair""", (token,)).fetchall()
        return {r[0]: dict(zip(("choice", "reason", "submitted_at", "revision"), r[1:])) for r in rows}

    def overview(self, token):
        self.check_session(token)
        votes = self.latest(token)
        indices = sorted(range(len(self.data.pairs)), key=lambda i: self.rank(token, "sequence", i))
        return {"title": self.data.title, "dataset": self.fingerprint,
                "pairs": [{"index": i, "vote": votes.get(i)} for i in indices]}

    def pair(self, token, index):
        order = self.order(token, index)
        pair = self.data.pairs[index]
        candidates = []
        for j in order:
            candidate = pair.candidates[j]
            candidates.append({"task": candidate.task, "response": candidate.response,
                "sections": [s.model_dump() for s in candidate.sections],
                "artifacts": [{"index": k, "label": a.label,
                               "bytes": self.files[index, j, k].stat().st_size}
                              for k, a in enumerate(candidate.artifacts)]})
        return {"requirement": pair.requirement, "candidates": candidates,
                "vote": self.latest(token).get(index)}

    def save(self, token, decision):
        self.order(token, decision.pair)
        with self.connect() as db:
            db.execute("INSERT INTO votes (session, pair, choice, reason, submitted_at) VALUES (?, ?, ?, ?, ?)",
                       (token, decision.pair, decision.choice, decision.reason, now()))
        return self.latest(token)[decision.pair]

    def artifact(self, token, pair, side, index):
        if side not in (0, 1):
            raise ValueError("Unknown side")
        j = self.order(token, pair)[side]
        try:
            return self.files[pair, j, index]
        except KeyError:
            raise ValueError("Unknown artifact") from None

    def export(self):
        """Researcher-only export; never exposed through the reviewer HTTP API."""
        with self.connect() as db:
            sessions = db.execute("SELECT id FROM sessions ORDER BY created_at, id").fetchall()
            rows = db.execute("SELECT revision, session, pair, choice, reason, submitted_at FROM votes ORDER BY revision").fetchall()
        reviewers = {r[0]: n for n, r in enumerate(sessions, 1)}
        history, latest = [], {}
        for revision, token, index, choice, reason, stamp in rows:
            order = self.order(token, index)
            pair = self.data.pairs[index]
            winner = order[0 if choice == "A" else 1]
            row = {"reviewer": reviewers[token], "pair_id": pair.id, "choice": choice,
                   "a_candidate": order[0], "b_candidate": order[1], "winner_candidate": winner,
                   "a_source": pair.candidates[order[0]].source,
                   "b_source": pair.candidates[order[1]].source,
                   "winner_source": pair.candidates[winner].source,
                   "reason": reason, "submitted_at": stamp, "revision": revision}
            history.append(row)
            latest[token, index] = row
        return {"dataset_sha256": self.fingerprint, "seed": self.seed, "unit": "task_pair",
                "reviewers": len(sessions), "pairs_per_reviewer": len(self.data.pairs),
                "decisions": list(latest.values()), "history": history}


def make_server(store, host="127.0.0.1", port=8877):
    html = inject_katex(HTML).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Artifact URLs contain review recovery codes.

        def send(self, code, data, content_type="application/json; charset=utf-8"):
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; font-src data:; connect-src 'self'; img-src blob: data:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlsplit(self.path)
            query = parse_qs(route.query)
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            try:
                if route.path == "/":
                    return self.send(200, html, "text/html; charset=utf-8")
                if route.path == "/api/overview":
                    return self.send(200, store.overview(token))
                if route.path == "/api/pair":
                    return self.send(200, store.pair(token, int(query["index"][0])))
                if route.path == "/api/artifact":
                    path = store.artifact(query["session"][0], int(query["pair"][0]),
                                          int(query["side"][0]), int(query["index"][0]))
                    with path.open("rb") as handle:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(path.stat().st_size))
                        filename = quote("artifact" + path.suffix, safe="")
                        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + filename)
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        shutil.copyfileobj(handle, self.wfile)
                    return
                self.send(404, {"error": "Not found"})
            except PermissionError as exc:
                self.send(403, {"error": str(exc)})
            except (ValueError, KeyError) as exc:
                self.send(400, {"error": str(exc)})

        def do_POST(self):
            try:
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                    raise PermissionError("Cross-origin submission rejected")
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                if self.path == "/api/session":
                    return self.send(200, {"session": store.new_session()})
                if self.path == "/api/vote":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1_048_576:
                        raise ValueError("Invalid submission size")
                    decision = Decision.model_validate_json(self.rfile.read(length))
                    return self.send(200, store.save(token, decision))
                self.send(404, {"error": "Not found"})
            except PermissionError as exc:
                self.send(403, {"error": str(exc)})
            except ValueError:
                self.send(400, {"error": "提交无效：必须选择 A 或 B，理由须为文本。"})

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path, help="Comparison JSON; attachments are relative to its directory")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--export", type=Path, help="Export latest decisions and revision history, then exit")
    args = parser.parse_args()
    if args.export and not args.database.is_file():
        parser.error("Export requires an existing review database")
    store = ReviewStore(args.data, args.database, args.seed)
    if args.export:
        with args.export.open("x", encoding="utf-8") as handle:
            json.dump(store.export(), handle, ensure_ascii=False, indent=2)
        return
    server = make_server(store, args.host, args.port)
    print(f"Human review: http://{args.host}:{server.server_port} ({len(store.data.pairs)} pairs)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
