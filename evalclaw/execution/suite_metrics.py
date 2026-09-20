"""Declared suite metrics over original task units, preserving raw results."""
from __future__ import annotations

import json
from collections import defaultdict

from .components import JsonComponent


def aggregate_metrics(suite, results):
    tasks = {t.id: t for t in suite.tasks}
    output = []
    for definition in suite.evaluation_plan:
        groups = defaultdict(list)
        seen = set()
        for result in results:
            key = (result.target_id, result.item_id)
            if key in seen:
                raise ValueError("Repeated executions must be explicitly aggregated before suite metrics")
            seen.add(key)
            task = tasks[result.item_id]
            labels = {field: task.annotations.get(field) for field in definition.group_by}
            groups[(result.target_id, json.dumps(labels, sort_keys=True))].append(result)
        for (target_id, group), rows in groups.items():
            entry = {"id": definition.id, "target_id": target_id, "group": json.loads(group),
                     "unit": "task", "total": len(rows), "valid": 0, "status": "valid"}
            def metric(row, name):
                if row.error or row.episode is None:
                    return None
                return next((m.value for m in row.episode.metrics if m.metric == name and m.status == "valid"), None)
            try:
                if definition.aggregation == "component":
                    assets = {a.id: a for task in suite.tasks for a in task.assets}
                    component = JsonComponent(definition.component, list(assets.values()))
                    try:
                        entry["raw"] = component.call("aggregate", {"tasks": [tasks[r.item_id].model_dump(mode="json") for r in rows],
                            "results": [r.model_dump(mode="json") for r in rows], "group": json.loads(group)})
                    finally:
                        component.close()
                    entry["valid"] = len([r for r in rows if not r.error])
                elif definition.aggregation == "micro":
                    pairs = [(metric(r, definition.numerator), metric(r, definition.denominator)) for r in rows]
                    pairs = [(n, d) for n, d in pairs if n is not None and d is not None]
                    numerator, denominator = sum(n for n, _ in pairs), sum(d for _, d in pairs)
                    entry.update(numerator=numerator, denominator=denominator, valid=len(pairs))
                    entry["value"] = numerator / denominator if denominator else None
                else:
                    values = [metric(r, definition.metric) for r in rows]
                    values = [v for v in values if v is not None]
                    entry["valid"] = len(values)
                    entry["value"] = (sum(values) / len(values) if definition.aggregation == "mean" else sum(values)) if values else None
                if entry["valid"] < entry["total"]:
                    entry["status"] = "incomplete"
            except Exception as exc:
                entry.update(status="error", error=f"{type(exc).__name__}: {exc}")
            output.append(entry)
    return output
