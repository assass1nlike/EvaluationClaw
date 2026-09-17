"""Check the saved experimental attributes under a 256 MiB address-space limit."""

import json
import math
import os
from pathlib import Path
import random
import resource
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upstream"))
from difficulty import difficulty_bands


def seed_everything(seed):
    random.seed(seed)
    if os.environ.get("PYTHONHASHSEED") != str(seed):
        os.environ["PYTHONHASHSEED"] = str(seed)
        os.execv(sys.executable, [sys.executable, *sys.argv])


def main():
    seed_everything(42)
    limit = 256 * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    results = {"seed": 42, "address_space_limit_bytes": limit, "runs": {}}
    for name in ("knowledge", "data-analysis", "instruction-following"):
        path = next((ROOT / "runs" / name).glob("API_Com_syn/*/*/attr/raw_data/*/attrs/attr3.json"))
        attributes = json.loads(path.read_text())
        seed_everything(42)
        tracemalloc.start()
        started = time.perf_counter()
        bands = difficulty_bands(attributes)
        build_seconds = time.perf_counter() - started
        total = math.prod(len(values) for values in attributes.values())
        assert len(bands[0].combinations) == total
        size = total - total // 2
        for i, band in enumerate(bands):
            assert len(band) == int((i + 1) / 10 * size) - int(i / 10 * size)
            for _ in range(100):
                combination = random.choice(band)
                assert list(combination) == list(attributes)
                for key, value in combination.items():
                    assert value in [v for v, _ in attributes[key]]
        seconds = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results["runs"][name] = {
            "attributes": str(path.relative_to(ROOT)), "combinations": total,
            "count_states": sum(len(counts) for counts in bands[0].combinations.counts),
            "build_seconds": build_seconds, "build_and_1000_draws_seconds": seconds,
            "peak_traced_bytes": peak,
            "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "band_sizes": [len(band) for band in bands],
        }
        del bands, band
    output = ROOT / "runs/difficulty-check"
    output.mkdir(exist_ok=True)
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
