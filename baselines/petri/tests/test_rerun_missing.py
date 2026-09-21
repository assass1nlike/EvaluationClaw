import importlib.util
import json
from pathlib import Path
import signal
import threading

from petri.scorers.prompts import DIMENSIONS

spec = importlib.util.spec_from_file_location("rerun_missing", Path(__file__).parents[1] / "scripts/rerun_missing.py")
rerun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rerun)


def test_rerun_missing_preserves_seeds_source_and_unselected_results(tmp_path, monkeypatch):
    original, output = tmp_path / "original", tmp_path / "rerun"
    (original / "source").mkdir(parents=True)
    (original / "source/sha256.json").write_text("{}")
    (original / "config.json").write_text(json.dumps({"finished_at": "finished", "seeds": list(range(42, 62)),
                                                     "options": ["--sol-rpm", "50"]}))
    selected = {(7, 2), (7, 16), (7, 19), (9, 14), (9, 15), (13, 6), (13, 7)}
    before = {}
    for req in rerun.REQUIREMENTS:
        directory = original / f"requirement-{req:02d}"
        directory.mkdir()
        records = [{"epoch": epoch, "seed": epoch + 41, "exit_code": 0,
                    "score": 8, "native_scores": {dim: 1 for dim in DIMENSIONS},
                    "output": f"requirement-{req:02d}/epoch-{epoch:02d}"} for epoch in range(1, 21)]
        for rec in records:
            if (req, rec["epoch"]) in selected:
                if rec["epoch"] % 2:
                    rec["score"] = None
                else:
                    rec["native_scores"] = {}
        p = directory / "summary.json"
        p.write_text(json.dumps({"epochs": records}))
        before[p] = p.read_bytes()
    barrier = threading.Barrier(7)
    calls = []

    def execute(batch, req, epoch, seed, options):
        assert options == ["--sol-rpm", "50"]
        assert seed == epoch + 41
        assert (batch / "source/sha256.json").read_text() == "{}"
        calls.append((req, epoch))
        barrier.wait(timeout=10)
        return {"epoch": epoch, "seed": seed, "exit_code": 0, "status": "success", "score": 9,
                "native_scores": {dim: 2 for dim in DIMENSIONS},
                "output": f"requirement-{req:02d}/epoch-{epoch:02d}"}

    monkeypatch.setattr(rerun, "run_epoch", execute)
    monkeypatch.setattr(rerun, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr("sys.argv", ["rerun_missing.py", str(original), "--output-dir", str(output)])
    prior = signal.getsignal(signal.SIGHUP)
    try:
        assert rerun.main() == 0
        assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGHUP, prior)
    assert set(calls) == selected
    assert all(p.read_bytes() == content for p, content in before.items())
    summaries = json.loads((output / "summary.json").read_text())
    for req, summary in summaries.items():
        assert summary["performance"]["n"] == 20
        for rec in summary["epochs"]:
            assert rec["score"] == (9 if (int(req), rec["epoch"]) in selected else 8)
    assert json.loads((output / "config.json").read_text())["still_missing"] == []
