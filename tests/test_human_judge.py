import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from evalclaw.reporting.human_judge import Decision, ReviewStore, make_server


@pytest.fixture
def data(tmp_path):
    attachment = tmp_path / "file.txt"
    attachment.write_text("complete evidence\n" + "a" * 100_000)
    value = {"title": "Comparison", "pairs": [
        {"id": "private-id", "requirement": "Evaluate reasoning", "candidates": [
            {"source": "PRIVATE_SOURCE_ONE", "task": "Question one", "response": "Response one",
             "artifacts": [{"label": "Evidence", "path": "file.txt"}]},
            {"source": "PRIVATE_SOURCE_TWO", "task": {"prompt": "Question two"}, "response": None}
        ]}
    ]}
    path = tmp_path / "pairs.json"
    path.write_text(json.dumps(value))
    return path


def test_blind_mapping_survives_restart_and_export_tracks_revisions(data, tmp_path):
    database = tmp_path / "votes.sqlite"
    store = ReviewStore(data, database)
    token = store.new_session()
    original = store.pair(token, 0)
    serialized = json.dumps(original)
    for private in ("PRIVATE_SOURCE_ONE", "PRIVATE_SOURCE_TWO", "private-id", "file.txt", str(tmp_path)):
        assert private not in serialized
    store.save(token, Decision(pair=0, choice="A", reason="First"))
    restarted = ReviewStore(data, database)
    assert restarted.order(token, 0) == store.order(token, 0)
    assert restarted.overview(token)["pairs"][0]["vote"]["choice"] == "A"
    restarted.save(token, Decision(pair=0, choice="B", reason="Revised"))
    export = restarted.export()
    assert len(export["decisions"]) == 1
    assert len(export["history"]) == 2
    selected = restarted.order(token, 0)[1]
    assert export["decisions"][0]["winner_source"] == store.data.pairs[0].candidates[selected].source
    assert token not in json.dumps(export)
    assert restarted.pair(token, 0)["candidates"] == original["candidates"]


def test_invalid_choice_or_pair_never_counts_as_vote(data, tmp_path):
    store = ReviewStore(data, tmp_path / "votes.sqlite")
    token = store.new_session()
    with pytest.raises(ValidationError):
        Decision(pair=0, choice="tie")
    with pytest.raises(ValueError):
        store.save(token, Decision(pair=1, choice="A"))
    with pytest.raises(PermissionError):
        store.save("unknown", Decision(pair=0, choice="A"))
    assert store.export()["decisions"] == []
    assert store.overview(token)["pairs"][0]["vote"] is None


def test_seed_data_and_attachment_changes_require_new_batch(data, tmp_path):
    database = tmp_path / "votes.sqlite"
    ReviewStore(data, database)
    with pytest.raises(ValueError, match="changed"):
        ReviewStore(data, database, seed=43)
    (tmp_path / "file.txt").write_text("changed evidence")
    with pytest.raises(ValueError, match="changed"):
        ReviewStore(data, database)


def test_attachment_cannot_escape_import_directory(data, tmp_path):
    value = json.loads(data.read_text())
    value["pairs"][0]["candidates"][0]["artifacts"][0]["path"] = "../secret.txt"
    data.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="inside the data directory"):
        ReviewStore(data, tmp_path / "votes.sqlite")


def test_concurrent_reviewers_are_isolated(data, tmp_path, monkeypatch):
    store = ReviewStore(data, tmp_path / "votes.sqlite")
    fixed_tokens = iter(f"reviewer-{i}" for i in range(16))
    monkeypatch.setattr("evalclaw.reporting.human_judge.secrets.token_urlsafe", lambda _: next(fixed_tokens))
    tokens = [store.new_session() for _ in range(16)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda token: store.save(token, Decision(pair=0, choice="A", reason=token)), tokens))
    for token in tokens:
        assert store.pair(token, 0)["vote"]["reason"] == token
    assert len(store.export()["decisions"]) == 16
    assert {tuple(store.order(t, 0)) for t in tokens} == {(0, 1), (1, 0)}


def test_http_full_evidence_and_blind_endpoints(data, tmp_path):
    store = ReviewStore(data, tmp_path / "votes.sqlite")
    server = make_server(store, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as client:
            assert client.get("/").status_code == 200
            assert client.get("/api/overview").status_code == 403
            token = client.post("/api/session").json()["session"]
            client.headers["Authorization"] = "Bearer " + token
            pair = client.get("/api/pair?index=0").json()
            side = next(i for i, c in enumerate(pair["candidates"]) if c["artifacts"])
            response = client.get("/api/artifact", params={"session": token, "pair": 0, "side": side, "index": 0})
            assert response.content == (tmp_path / "file.txt").read_bytes()
            assert "file.txt" not in response.headers["Content-Disposition"]
            assert client.get("/api/export").status_code == 404
            assert client.get("/../pairs.json").status_code == 404
            assert client.post("/api/vote", json={"pair": 0, "choice": "tie"}).status_code == 400
            assert client.post("/api/vote", json={"pair": 0, "choice": "B", "reason": "More suitable"}).status_code == 200
            assert client.get("/api/overview").json()["pairs"][0]["vote"]["choice"] == "B"
            assert client.post("/api/vote", headers={"Origin": "https://elsewhere.invalid"}, json={"pair": 0, "choice": "A"}).status_code == 403
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
