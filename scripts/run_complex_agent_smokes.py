"""Run a small suite of more complex EvaluationClaw agent tasks.

The suite uses scripted model outputs so it validates EvaluationClaw's
environment lifecycle, tool protocol, hidden scoring, and cleanup behavior
without spending model API budget.
"""
from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evalclaw.execution.docker import docker_status
from evalclaw.runners import agent as runner_agent
from evalclaw.runners.agent import run_agent_interaction
from evalclaw.types import BenchmarkConfig, BenchmarkItem, TargetModelConfig, TaskType
from scripts.run_vm_agent_smoke import (
    BASE_IMAGE,
    SEED_ISO,
    SERIAL_LOG,
    create_seed_iso,
    download_base_image,
    print_serial_log_tail,
)

OUTPUT_DIR = Path(r"D:\localwork\vm_backends\complex_agent_smokes")
RESULT_PATH = OUTPUT_DIR / "complex_agent_smoke_results.json"


def make_code_repair_item() -> tuple[BenchmarkItem, list[dict[str, Any]], BenchmarkConfig]:
    bad_solution = """\
def summarize_orders(orders):
    total = sum(order["amount"] for order in orders)
    return {"count": len(orders), "total": total, "average": total / len(orders)}
"""
    fixed_once = """\
def summarize_orders(orders):
    total = sum(order["amount"] for order in orders)
    if not orders:
        return {"count": 0, "total": 0, "average": 0}
    return {"count": len(orders), "total": total, "average": total / len(orders)}
"""
    fixed_final = """\
from decimal import Decimal


def summarize_orders(orders):
    total = Decimal("0")
    valid_count = 0
    for order in orders:
        if order.get("status") == "cancelled":
            continue
        total += Decimal(str(order.get("amount", 0)))
        valid_count += 1
    if valid_count == 0:
        return {"count": 0, "total": "0.00", "average": "0.00"}
    average = total / valid_count
    return {
        "count": valid_count,
        "total": f"{total:.2f}",
        "average": f"{average:.2f}",
    }
"""
    tests = """\
from solution import summarize_orders


orders = [
    {"amount": "10.10", "status": "paid"},
    {"amount": "5.00", "status": "cancelled"},
    {"amount": "2.20", "status": "paid"},
]
assert summarize_orders(orders) == {"count": 2, "total": "12.30", "average": "6.15"}
assert summarize_orders([]) == {"count": 0, "total": "0.00", "average": "0.00"}
assert summarize_orders([{"amount": "3.00", "status": "cancelled"}]) == {
    "count": 0,
    "total": "0.00",
    "average": "0.00",
}
"""
    item = BenchmarkItem(
        id="code_repair_hidden_business_rules",
        dimension_id="iterative_code_agent",
        task_type=TaskType.agent,
        prompt=(
            "Repair summarize_orders in solution.py. It must ignore cancelled orders, handle empty input, "
            "avoid floating point money errors, and pass the hidden tests. Inspect files and run tests."
        ),
        rubric="Full credit requires passing hidden tests after iterative repair.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "visible_files": {"solution.py": bad_solution},
                "hidden_files": {"tests.py": tests},
                "test_command": "python3 tests.py",
                "max_steps": 7,
                "timeout": 10,
            }
        },
        tags=["agent", "docker_workspace", "hidden_tests"],
    )
    actions = [
        {"action": "read_file", "args": {"path": "solution.py"}},
        {"action": "write_file", "args": {"path": "solution.py", "content": fixed_once}},
        {"action": "run_tests", "args": {}},
        {"action": "write_file", "args": {"path": "solution.py", "content": fixed_final}},
        {"action": "run_tests", "args": {}},
    ]
    return item, actions, BenchmarkConfig(environment_claw=False)


def make_docker_item() -> tuple[BenchmarkItem, list[dict[str, Any]], BenchmarkConfig]:
    fixed_script = """\
#!/bin/sh
input="$1"
tr '[:upper:]' '[:lower:]' < "$input" \
  | tr -cs '[:alnum:]' '\\n' \
  | sed '/^$/d' \
  | sort \
  | uniq -c \
  | sort -nr -k1,1 -k2,2 \
  | awk 'NR<=3 {print $2 ":" $1}'
"""
    tests = """\
printf 'Apple banana apple. Carrot banana apple! carrot delta\n' > sample.txt
sh analyze.sh sample.txt > result.txt
grep -Fx 'apple:3' result.txt
grep -Fx 'banana:2' result.txt
grep -Fx 'carrot:2' result.txt
"""
    item = BenchmarkItem(
        id="docker_cli_data_processing",
        dimension_id="containerized_tool_use",
        task_type=TaskType.agent,
        prompt=(
            "Repair analyze.sh inside the container. The command-line script should tokenize text, "
            "count words case-insensitively, and print the top three words as word:count lines."
        ),
        rubric="Full credit requires passing hidden container tests.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "image": "ubuntu:22.04",
                "pull_image": False,
                "network": "none",
                "visible_files": {
                    "analyze.sh": "#!/bin/sh\ncat \"$1\"\n",
                    "README.md": "Implement analyze.sh for CLI word frequency analysis.\n",
                },
                "hidden_files": {"tests.sh": tests},
                "test_command": "sh tests.sh",
                "max_steps": 7,
                "timeout": 20,
            }
        },
        tags=["agent", "docker_workspace", "cli"],
    )
    actions = [
        {"action": "list_files", "args": {}},
        {"action": "read_file", "args": {"path": "analyze.sh"}},
        {"action": "run_command", "args": {"command": "sh --version || true", "timeout": 5}},
        {"action": "write_file", "args": {"path": "analyze.sh", "content": fixed_script}},
        {"action": "run_tests", "args": {}},
    ]
    return item, actions, BenchmarkConfig(environment_claw=False)


def make_vm_item() -> tuple[BenchmarkItem, list[dict[str, Any]], BenchmarkConfig]:
    item = BenchmarkItem(
        id="vm_multi_artifact_session",
        dimension_id="vm_desktop_bridge",
        task_type=TaskType.agent,
        prompt=(
            "Inside the VM session, create two artifacts: /reports/summary.txt containing "
            "'VM complex success' and /reports/checklist.txt containing 'alpha' and 'beta'. "
            "Then run the environment evaluation."
        ),
        rubric="Full credit requires both VM files to exist and contain the expected text.",
        metadata={
            "agent_env": {
                "type": "gui",
                "requires_vm": True,
                "vm_provider_url": "local://qemu",
                "vm": {
                    "disk_image": str(BASE_IMAGE),
                    "seed_iso": str(SEED_ISO),
                    "disk_format": "qcow2",
                    "bridge": {"guest_port": 7766},
                    "memory_mb": 1024,
                    "cpus": 1,
                    "bridge_wait_timeout": 600,
                    "accel": "tcg",
                    "serial_log": str(SERIAL_LOG),
                },
                "session": {"application": "minimal_http_bridge", "task": "multi_artifact"},
                "evaluation": {
                    "expected_files": [
                        {"path": "reports/summary.txt", "contains": ["VM complex success"]},
                        {"path": "reports/checklist.txt", "contains": ["alpha", "beta"]},
                    ]
                },
                "max_steps": 4,
                "timeout": 20,
            }
        },
        tags=["agent", "vm", "gui"],
    )
    actions = [
        {
            "action": "write_file",
            "args": {"path": "/reports/summary.txt", "content": "VM complex success\ncreated by scripted agent\n"},
        },
        {"action": "write_file", "args": {"path": "/reports/checklist.txt", "content": "alpha\nbeta\n"}},
        {"action": "evaluate", "args": {}},
    ]
    config = BenchmarkConfig(
        vm_provider_url="local://qemu",
        vm_provider_timeout_s=660,
        vm_provider_destroy_on_cleanup=True,
        environment_claw=False,
    )
    return item, actions, config


def run_scripted_item(
    item: BenchmarkItem,
    actions: Iterable[dict[str, Any]],
    config: BenchmarkConfig,
) -> dict[str, Any]:
    target = TargetModelConfig(provider="mock", model=f"{item.id}-scripted-agent")
    scripted_actions = iter(actions)

    def fake_call_target_model(*args: Any, **kwargs: Any) -> str:
        try:
            return json.dumps(next(scripted_actions))
        except StopIteration:
            return json.dumps({"action": "final", "args": {"answer": "done"}})

    original = runner_agent.call_target_model
    runner_agent.call_target_model = fake_call_target_model
    started = time.monotonic()
    try:
        raw, score, reasoning = run_agent_interaction(item, target, config)
        return {
            "item_id": item.id,
            "status": "passed" if score >= 1.0 else "failed",
            "score": score,
            "reasoning": reasoning,
            "elapsed_s": round(time.monotonic() - started, 1),
            "raw": json.loads(raw),
        }
    except Exception as exc:
        return {
            "item_id": item.id,
            "status": "error",
            "score": 0.0,
            "error": str(exc),
            "elapsed_s": round(time.monotonic() - started, 1),
        }
    finally:
        runner_agent.call_target_model = original


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tasks: list[tuple[str, tuple[BenchmarkItem, list[dict[str, Any]], BenchmarkConfig]]] = [
        ("docker_code_repair", make_code_repair_item()),
    ]

    docker = docker_status(timeout_s=10)
    if docker.available:
        tasks.append(("docker_shell", make_docker_item()))
    else:
        print(f"Skipping docker task because Docker is unavailable: {docker.error}", flush=True)

    try:
        download_base_image()
        create_seed_iso()
        tasks.append(("vm_gui", make_vm_item()))
    except Exception as exc:
        print(f"Skipping VM task because VM setup failed: {exc}", flush=True)

    results = []
    for kind, (item, actions, config) in tasks:
        print(f"\n=== Running {kind}: {item.id} ===", flush=True)
        result = run_scripted_item(item, actions, config)
        results.append(result)
        print(json.dumps({k: result[k] for k in result if k not in {"raw"}}, ensure_ascii=False, indent=2), flush=True)
        if item.id.startswith("vm_") and result["status"] == "error":
            print_serial_log_tail()

    summary = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
        "passed": sum(1 for result in results if result["status"] == "passed"),
        "total_run": len(results),
    }
    RESULT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote results to {RESULT_PATH}", flush=True)
    if any(result["status"] != "passed" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
