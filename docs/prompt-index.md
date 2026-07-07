# Prompt Index

This page links directly to the prompts that drive EvaluationClaw's planning,
generation, QC, and improvement stages.

## Planner

| Stage | File | Line | Purpose |
| --- | --- | --- | --- |
| Goal translation | [evalclaw/planning/planner.py](../evalclaw/planning/planner.py) | 25 | Translate non-English goals into English before planning. |
| Main planning prompt | [evalclaw/planning/planner.py](../evalclaw/planning/planner.py) | 36 | Turn a natural-language goal into a structured `EvalSpec`, including task-agent requirements and optional reference-model pairwise planning. |
| Task-agent schema guidance | [evalclaw/task_agent.py](../evalclaw/task_agent.py) | 56 | Standardized `metadata.task_agent` generation guidance reused by Planner, Generator, and Planner review prompts. |

## Deep Research

| Stage | File | Line | Purpose |
| --- | --- | --- | --- |
| Initial query generation | [evalclaw/prompts/research.py](../evalclaw/prompts/research.py) | 4 | Generate the initial web-search query set from the evaluation goal. |
| Findings compression | [evalclaw/prompts/research.py](../evalclaw/prompts/research.py) | 22 | Compress raw search syntheses and fetched page text into concise findings. |
| Gap reflection | [evalclaw/prompts/research.py](../evalclaw/prompts/research.py) | 39 | Check findings against the `ResearchBrief` schema, emit gaps and follow-up queries or declare done. |
| Brief synthesis | [evalclaw/prompts/research.py](../evalclaw/prompts/research.py) | 64 | Synthesize the final structured `ResearchBrief` JSON from accumulated findings. |

## Generation

| Stage | File | Line | Purpose |
| --- | --- | --- | --- |
| Dimension item-generation prompt | [evalclaw/generator.py](../evalclaw/generator.py) | 28 | Generate or synthesize items for one dimension, including task type, source strategy, pairwise preference items, and `metadata.task_agent` for complex interactive items. |

## Pre-Run Review

| Stage | File | Line | Purpose |
| --- | --- | --- | --- |
| Planner dataset review prompt | [evalclaw/planning/loop.py](../evalclaw/planning/loop.py) | 31 | Review the generated dataset before any target model run, including optional human feedback, pairwise reference fit, task-agent completeness, and delete/move/add/merge/split/refill decisions. |

## Quality Control

| Stage | File | Line | Purpose |
| --- | --- | --- | --- |
| QC gate prompt | [evalclaw/quality/qc.py](../evalclaw/quality/qc.py) | 24 | Judge whether the benchmark plan and items are coherent, executable, adequately covered, and well specified for pairwise and task-agent interactive items. |

## Loop 3

| Stage | File | Line | Purpose |
| --- | --- | --- | --- |
| Loop 3 improvement prompt | [evalclaw/improver.py](../evalclaw/improver.py) | 28 | Diagnose weak spots after the first run and propose targeted regeneration or expansion actions. |

## Notes

- The links above intentionally open the file only. Some editors treat `:line`
  as part of the filename in Markdown links, so line numbers are listed in a
  separate column.
- If you want the same index in Chinese, keep this file and replace the
  descriptions in place.

## Relative Paths

If your editor does not resolve the clickable links above, open these files from
the repository root and jump to the listed line:

| Stage | Relative path |
| --- | --- |
| Goal translation | `evalclaw/planning/planner.py`, line 25 |
| Main planning prompt | `evalclaw/planning/planner.py`, line 36 |
| Deep-research prompts | `evalclaw/prompts/research.py`, lines 4, 22, 39, 64 |
| Task-agent schema guidance | `evalclaw/task_agent.py`, line 56 |
| Dimension item-generation prompt | `evalclaw/generator.py`, line 28 |
| Planner dataset review prompt | `evalclaw/planning/loop.py`, line 31 |
| QC gate prompt | `evalclaw/quality/qc.py`, line 24 |
| Loop 3 improvement prompt | `evalclaw/improver.py`, line 28 |
