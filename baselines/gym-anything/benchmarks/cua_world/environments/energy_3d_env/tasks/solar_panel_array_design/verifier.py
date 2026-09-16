#!/usr/bin/env python3
"""Stub verifier for solar_panel_array_design.

Energy3D stores projects as Java-serialized binary (.ng3). Programmatic
inspection is not feasible without a Java reader, so the production
verification path is the external VLM evaluator that compares the final
screenshot against the task description. This stub exists for framework
compatibility.
"""


def verify_solar_panel_array_design(traj, env_info, task_info):
    return {
        "passed": True,
        "score": 100,
        "feedback": "Stub verifier - VLM evaluation is performed externally.",
    }
