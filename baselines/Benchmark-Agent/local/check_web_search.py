"""Exercise the configured framework search tool and retain its provider usage."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from local.run_with_usage import UsageRecorder, observe_calls
from tools.executor_tools.implementations.web_tools import web_search


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--query", required=True)
    parser.add_argument("--image")
    args = parser.parse_args()
    recorder = UsageRecorder(args.output)
    record = {"query": args.query, "image": args.image}
    status = "failed"
    try:
        with observe_calls(recorder):
            record["result"] = web_search(args.query, image_paths=[args.image] if args.image else None)
        status = "completed"
        print(json.dumps(record["result"], ensure_ascii=False))
    except Exception as exc:
        record["error_type"] = type(exc).__name__
        # Provider exception strings can contain credentials or request headers.
        print(f"Search probe failed ({type(exc).__name__}); inspect the usage records for response status.")
    finally:
        recorder.finish(status)
        (recorder.directory / "probe.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(recorder.directory)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
