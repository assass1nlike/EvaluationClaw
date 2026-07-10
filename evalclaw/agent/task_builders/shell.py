"""Shell and runtime debugging fallback agent tasks."""
from __future__ import annotations

from ...types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    AgentScoringSpec,
    AgentTask,
    AgentTaskBlueprint,
    EvalDimension,
)
from ..planning import _contains_any
from .base import _agent_system_prompt, _task_id, _task_title


def _shell_debugging_task_for_blueprint(
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    *,
    index: int = 1,
) -> AgentTask:
    variants = [
        {
            "prompt": (
                "The repository healthcheck fails because app.py mishandles ordinary text files. Use shell "
                "diagnostics and file edits to make the hidden healthcheck tests pass."
            ),
            "scoring": {
                "instructions": "Score by running hidden tests inside the docker_workspace.",
                "pass": "The healthcheck succeeds and reports the correct number of records.",
                "partial": "The agent runs useful diagnostics but the final tests still fail.",
                "fail": "The agent never diagnoses the shell/runtime failure.",
            },
            "visible": {
                "healthcheck.sh": (
                    "#!/bin/sh\n"
                    "set -eu\n"
                    "python app.py --check data/input.txt\n"
                ),
                "app.py": (
                    "import argparse\n"
                    "from pathlib import Path\n\n"
                    "parser = argparse.ArgumentParser()\n"
                    "parser.add_argument('--check')\n"
                    "args = parser.parse_args()\n\n"
                    "path = Path(args.check)\n"
                    "lines = path.read_text().split('\\n')\n"
                    "print(f'records={len(lines)}')\n"
                    "if '' in lines:\n"
                    "    raise SystemExit('blank record found')\n"
                ),
                "data/input.txt": "alpha\nbeta\ngamma\n",
            },
            "hidden": {
                "tests.py": (
                    "import subprocess\n"
                    "import sys\n\n"
                    "proc = subprocess.run(['sh', 'healthcheck.sh'], text=True, capture_output=True)\n"
                    "assert proc.returncode == 0, proc.stdout + proc.stderr\n"
                    "assert 'records=3' in proc.stdout\n"
                )
            },
        },
        {
            "prompt": (
                "Diagnose the Kubernetes incident packet and update rca.py so answer() identifies the failing "
                "service, root cause, and remediation. Use the provided logs/manifests, then run tests until they pass."
            ),
            "scoring": {
                "instructions": (
                    "Score by hidden RCA checks that verify the identified service, root cause, remediation, "
                    "and cited evidence files."
                ),
                "pass": (
                    "The RCA identifies payment-api, explains the readiness probe port mismatch between "
                    "8080 and 8081, recommends aligning the probe/container port, and cites the log and manifest."
                ),
                "partial": "The RCA identifies the affected service and some evidence but misses the exact port mismatch or remediation.",
                "fail": "The agent does not ground the RCA in the provided Kubernetes logs and manifests.",
            },
            "visible": {
                "logs/payment-api.log": (
                    "10:01 readiness probe failed: connect ECONNREFUSED 127.0.0.1:8080\n"
                    "10:02 payment-api pod restarted after config reload\n"
                    "10:03 upstream checkout requests returning 503\n"
                ),
                "manifests/payment-api.yaml": (
                    "service: payment-api\n"
                    "containerPort: 8081\n"
                    "readinessProbe:\n"
                    "  httpGet:\n"
                    "    path: /ready\n"
                    "    port: 8080\n"
                ),
                "rca.py": (
                    "def answer():\n"
                    "    return {'service': '', 'root_cause': '', 'remediation': '', 'evidence_files': []}\n"
                ),
            },
            "hidden": {
                "tests.py": (
                    "from rca import answer\n\n"
                    "result = answer()\n"
                    "text = ' '.join(str(v).lower() for v in result.values())\n"
                    "assert result['service'] == 'payment-api'\n"
                    "assert 'readiness' in text and 'port' in text and '8080' in text and '8081' in text\n"
                    "assert 'manifests/payment-api.yaml' in result['evidence_files']\n"
                    "assert 'logs/payment-api.log' in result['evidence_files']\n"
                )
            },
        },
        {
            "prompt": (
                "Triage the security artifact packet and update extract_iocs.py so answer() returns the command-and-control "
                "host, beacon interval, and suspicious user agent grounded in the provided PCAP summary. Run tests until they pass."
            ),
            "scoring": {
                "instructions": "Score by hidden IOC checks over the produced structured answer.",
                "pass": "The answer extracts the C2 host, beacon interval, user agent, and evidence file exactly.",
                "partial": "The answer extracts at least two correct indicators but misses one required IOC or citation.",
                "fail": "The agent does not identify the malicious flow from the packet summary.",
            },
            "visible": {
                "pcap_summary.txt": (
                    "flow 17: workstation -> updates.example.org GET /check user-agent Mozilla/5.0\n"
                    "flow 22: workstation -> c2-shadow.invalid POST /gate user-agent WinHttp-Stage interval=45s\n"
                    "flow 28: workstation -> cdn.example.org GET /asset.js user-agent Mozilla/5.0\n"
                ),
                "extract_iocs.py": (
                    "def answer():\n"
                    "    return {'c2_host': '', 'beacon_interval_s': 0, 'user_agent': '', 'evidence': []}\n"
                ),
            },
            "hidden": {
                "tests.py": (
                    "from extract_iocs import answer\n\n"
                    "result = answer()\n"
                    "assert result['c2_host'] == 'c2-shadow.invalid'\n"
                    "assert result['beacon_interval_s'] == 45\n"
                    "assert result['user_agent'] == 'WinHttp-Stage'\n"
                    "assert 'pcap_summary.txt' in result['evidence']\n"
                )
            },
        },
    ]
    full_text = " ".join(
        [dimension.id, dimension.name, dimension.description, dimension.approach, blueprint.title, blueprint.description]
    ).lower()
    if _contains_any(full_text, ("kubernetes", "k8s", "payment api", "root-cause", "root cause", "incident", "manifest")):
        kubernetes_variants = [
            variants[1],
            {
                "prompt": (
                    "Diagnose the Kubernetes autoscaling incident and update rca.py so answer() identifies the "
                    "failing service, root cause, and remediation. Use the provided HPA metrics and manifests, "
                    "then run tests until they pass."
                ),
                "scoring": {
                    "instructions": "Score by hidden RCA checks over autoscaling evidence and remediation.",
                    "pass": (
                        "The RCA identifies payment-api, explains that the HPA targets the wrong metric name "
                        "so replicas never scale under checkout load, recommends correcting the HPA metric, "
                        "and cites the HPA and metrics files."
                    ),
                    "partial": "The RCA identifies autoscaling as relevant but misses the exact metric mismatch or remediation.",
                    "fail": "The agent does not ground the RCA in the provided HPA and metric evidence.",
                },
                "visible": {
                    "manifests/payment-api-hpa.yaml": (
                        "apiVersion: autoscaling/v2\n"
                        "kind: HorizontalPodAutoscaler\n"
                        "metadata:\n"
                        "  name: payment-api\n"
                        "spec:\n"
                        "  scaleTargetRef:\n"
                        "    apiVersion: apps/v1\n"
                        "    kind: Deployment\n"
                        "    name: payment-api\n"
                        "  minReplicas: 2\n"
                        "  maxReplicas: 6\n"
                        "  metrics:\n"
                        "  - type: Pods\n"
                        "    pods:\n"
                        "      metric:\n"
                        "        name: http_requests_per_second\n"
                        "      target:\n"
                        "        type: AverageValue\n"
                        "        averageValue: \"50\"\n"
                    ),
                    "metrics/prometheus_snapshot.txt": (
                        "payment_api_requests_per_second{pod=\"payment-api-5f7\"} 180\n"
                        "payment_api_requests_per_second{pod=\"payment-api-6a2\"} 175\n"
                        "hpa_current_replicas{name=\"payment-api\"} 2\n"
                        "hpa_condition{name=\"payment-api\",reason=\"FailedGetPodsMetric\"} 1\n"
                    ),
                    "logs/checkout-errors.log": (
                        "10:14 checkout -> payment-api 503 upstream timeout\n"
                        "10:15 checkout -> payment-api 503 upstream timeout\n"
                        "10:16 payment-api saturated: queue_depth=124\n"
                    ),
                    "rca.py": (
                        "def answer():\n"
                        "    return {'service': '', 'root_cause': '', 'remediation': '', 'evidence_files': []}\n"
                    ),
                },
                "hidden": {
                    "tests.py": (
                        "from rca import answer\n\n"
                        "result = answer()\n"
                        "text = ' '.join(str(v).lower() for v in result.values())\n"
                        "assert result['service'] == 'payment-api'\n"
                        "assert 'hpa' in text and 'metric' in text\n"
                        "assert 'http_requests_per_second' in text and 'payment_api_requests_per_second' in text\n"
                        "assert 'manifests/payment-api-hpa.yaml' in result['evidence_files']\n"
                        "assert 'metrics/prometheus_snapshot.txt' in result['evidence_files']\n"
                    )
                },
            },
            {
                "prompt": (
                    "Diagnose the Kubernetes network-policy incident and update rca.py so answer() identifies "
                    "the affected service, root cause, and remediation. Use the provided policy, service, and "
                    "connection logs, then run tests until they pass."
                ),
                "scoring": {
                    "instructions": "Score by hidden RCA checks over network-policy evidence and remediation.",
                    "pass": (
                        "The RCA identifies payment-api, explains that a NetworkPolicy blocks ingress from "
                        "checkout because the podSelector/namespaceSelector does not match, recommends allowing "
                        "checkout traffic, and cites the policy and logs."
                    ),
                    "partial": "The RCA identifies a network-policy issue but misses the selector mismatch or evidence.",
                    "fail": "The agent does not ground the RCA in the provided Kubernetes network evidence.",
                },
                "visible": {
                    "manifests/payment-api-networkpolicy.yaml": (
                        "apiVersion: networking.k8s.io/v1\n"
                        "kind: NetworkPolicy\n"
                        "metadata:\n"
                        "  name: payment-api-ingress\n"
                        "spec:\n"
                        "  podSelector:\n"
                        "    matchLabels:\n"
                        "      app: payment-api\n"
                        "  ingress:\n"
                        "  - from:\n"
                        "    - podSelector:\n"
                        "        matchLabels:\n"
                        "          app: fraud-worker\n"
                        "    ports:\n"
                        "    - protocol: TCP\n"
                        "      port: 8080\n"
                    ),
                    "manifests/checkout-pod.yaml": (
                        "metadata:\n"
                        "  labels:\n"
                        "    app: checkout\n"
                        "spec:\n"
                        "  containers:\n"
                        "  - name: checkout\n"
                        "    image: checkout:stable\n"
                    ),
                    "logs/network.log": (
                        "checkout-7c9 -> payment-api:8080 connection timed out\n"
                        "fraud-worker-55a -> payment-api:8080 connected\n"
                        "payment-api readiness: ok\n"
                    ),
                    "rca.py": (
                        "def answer():\n"
                        "    return {'service': '', 'root_cause': '', 'remediation': '', 'evidence_files': []}\n"
                    ),
                },
                "hidden": {
                    "tests.py": (
                        "from rca import answer\n\n"
                        "result = answer()\n"
                        "text = ' '.join(str(v).lower() for v in result.values())\n"
                        "assert result['service'] == 'payment-api'\n"
                        "assert 'networkpolicy' in text or 'network policy' in text\n"
                        "assert 'checkout' in text and 'fraud-worker' in text\n"
                        "assert 'manifests/payment-api-networkpolicy.yaml' in result['evidence_files']\n"
                        "assert 'logs/network.log' in result['evidence_files']\n"
                    )
                },
            },
        ]
        variant = kubernetes_variants[(index - 1) % len(kubernetes_variants)]
    elif _contains_any(full_text, ("pcap", "malware", "security", "ioc", "wireshark", "ghidra")):
        variant = variants[2]
    else:
        variant = variants[(index - 1) % len(variants)]
    return AgentTask(
        id=_task_id(dimension, blueprint.task_family, index),
        dimension_id=dimension.id,
        title=_task_title(blueprint, index),
        description=(
            "A shell-oriented debugging task that benefits from command diagnostics and realistic workspace "
            "execution. The agent must inspect files, run commands, and patch the failure."
        ),
        task_family=blueprint.task_family,
        prompt=str(variant["prompt"]),
        system_prompt=_agent_system_prompt("docker_workspace"),
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.docker_workspace,
            image="python:3.11-slim",
            visible_files=variant["visible"],
            hidden_files=variant["hidden"],
            setup_commands=[],
            test_command="python3 tests.py",
            max_steps=10,
            timeout=20,
            network="none",
            resource_limits={"memory": "512m", "cpus": "1"},
        ),
        interaction={
            "max_turns": 10,
            "stop_condition": "Stop when hidden tests pass or the docker_workspace step limit is reached.",
        },
        scoring=AgentScoringSpec(
            method="deterministic",
            instructions=str(variant["scoring"]["instructions"]),
            pass_criteria=str(variant["scoring"]["pass"]),
            partial_criteria=str(variant["scoring"]["partial"]),
            fail_criteria=str(variant["scoring"]["fail"]),
        ),
        difficulty=dimension.target_difficulty,
        tags=[dimension.id, blueprint.task_family.value, "docker_workspace", "shell"],
    )
