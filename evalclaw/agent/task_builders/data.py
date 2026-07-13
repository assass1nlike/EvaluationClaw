"""Data-analysis fallback agent tasks."""
from __future__ import annotations

import json
from typing import Any

from ...types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    AgentScoringSpec,
    AgentTask,
    AgentTaskBlueprint,
    EvalDimension,
)
from ..goal_detection import _contains_any
from .base import _agent_system_prompt, _task_id, _task_title


def _data_analysis_task_for_blueprint(
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    *,
    index: int = 1,
) -> AgentTask:
    env_type = (
        AgentEnvironmentType.docker_workspace
        if blueprint.environment_type == AgentEnvironmentType.docker_workspace
        else AgentEnvironmentType.code_sandbox
    )
    env_kwargs: dict[str, Any] = {}
    if env_type == AgentEnvironmentType.docker_workspace:
        env_kwargs.update(
            {
                "image": "python:3.11-slim",
                "setup_commands": [],
                "network": "none",
                "resource_limits": {"memory": "512m", "cpus": "1"},
            }
        )
    variants = [
        {
            "prompt": (
                "Analyze data.csv and update analysis.py so answer() returns the requested metrics: top team by "
                "total profit, total north-region profit, south-region margin, and row count. Run tests until they pass."
            ),
            "visible": {
                "data.csv": (
                    "date,team,region,revenue,cost\n"
                    "2026-01-01,alpha,north,120,80\n"
                    "2026-01-02,beta,south,90,60\n"
                    "2026-01-03,alpha,north,150,90\n"
                    "2026-01-04,beta,south,130,100\n"
                    "2026-01-05,gamma,north,70,55\n"
                ),
                "analysis.py": (
                    "def answer():\n"
                    "    return {\n"
                    "        'top_team_by_profit': '',\n"
                    "        'north_profit': 0,\n"
                    "        'south_margin': 0.0,\n"
                    "        'rows_used': 0,\n"
                    "    }\n"
                ),
            },
            "hidden": {
                "tests.py": (
                    "from analysis import answer\n\n"
                    "result = answer()\n"
                    "assert result['top_team_by_profit'] == 'alpha'\n"
                    "assert result['north_profit'] == 115\n"
                    "assert abs(result['south_margin'] - (60 / 220)) < 1e-9\n"
                    "assert result['rows_used'] == 5\n"
                )
            },
        },
        {
            "prompt": (
                "Build a compact climate-emulation pipeline from train_climate.csv and test_forcings.csv. Fit any "
                "benchmark-safe baseline on the training rows only, predict tas and pr for the held-out ssp245 test "
                "grid, and write processed/test_predictions.csv, processed/metadata.json, submissions/kaggle_submission.csv, "
                "and workflow_manifest.json exactly as described in output_contract.json. Run tests until they pass."
            ),
            "visible": {
                "train_climate.csv": (
                    "scenario,month,y,x,co2,ch4,tas,pr\n"
                    "ssp126,1,0,0,410,1.9,4.20,0.569\n"
                    "ssp126,1,0,1,410,1.9,4.40,0.669\n"
                    "ssp126,1,1,0,410,1.9,4.60,0.769\n"
                    "ssp126,1,1,1,410,1.9,4.80,0.869\n"
                    "ssp370,2,0,0,425,2.0,4.45,0.620\n"
                    "ssp370,2,0,1,425,2.0,4.65,0.720\n"
                    "ssp370,2,1,0,425,2.0,4.85,0.820\n"
                    "ssp370,2,1,1,425,2.0,5.05,0.920\n"
                    "ssp585,3,0,0,440,2.2,4.70,0.672\n"
                    "ssp585,3,0,1,440,2.2,4.90,0.772\n"
                    "ssp585,3,1,0,440,2.2,5.10,0.872\n"
                    "ssp585,3,1,1,440,2.2,5.30,0.972\n"
                ),
                "test_forcings.csv": (
                    "scenario,month,y,x,co2,ch4\n"
                    "ssp245,4,0,0,432,2.1\n"
                    "ssp245,4,0,1,432,2.1\n"
                    "ssp245,4,1,0,432,2.1\n"
                    "ssp245,4,1,1,432,2.1\n"
                ),
                "output_contract.json": json.dumps(
                    {
                        "processed/test_predictions.csv": {
                            "columns": ["scenario", "month", "y", "x", "tas", "pr"],
                            "rows": 4,
                        },
                        "processed/metadata.json": {
                            "required_fields": ["model_family", "normalization_fit_on", "train_rows", "test_rows"],
                            "normalization_fit_on": "train",
                        },
                        "submissions/kaggle_submission.csv": {
                            "columns": ["id", "variable", "prediction"],
                            "rows": 8,
                        },
                        "workflow_manifest.json": {
                            "required_fields": ["inputs", "outputs", "commands_or_steps"],
                        },
                    },
                    indent=2,
                ),
                "README.md": (
                    "This compact fixture mirrors a larger climate-emulation task. Use only train_climate.csv for "
                    "fitting. The ssp245 target labels are hidden. Predictions must be reproducible and saved under "
                    "processed/ and submissions/ as specified."
                ),
                "pipeline.py": (
                    "def main():\n"
                    "    raise NotImplementedError('Build the climate-emulation pipeline and write outputs.')\n\n"
                    "if __name__ == '__main__':\n"
                    "    main()\n"
                ),
            },
            "hidden": {
                "tests.py": (
                    "import csv, json, math\n"
                    "from pathlib import Path\n\n"
                    "pred_path = Path('processed/test_predictions.csv')\n"
                    "meta_path = Path('processed/metadata.json')\n"
                    "sub_path = Path('submissions/kaggle_submission.csv')\n"
                    "manifest_path = Path('workflow_manifest.json')\n"
                    "for path in [pred_path, meta_path, sub_path, manifest_path]:\n"
                    "    assert path.is_file() and path.stat().st_size > 0, f'missing {path}'\n"
                    "rows = list(csv.DictReader(pred_path.open(newline='', encoding='utf-8-sig')))\n"
                    "assert len(rows) == 4\n"
                    "expected = {\n"
                    "    ('0', '0'): (4.72, 0.721),\n"
                    "    ('0', '1'): (4.92, 0.821),\n"
                    "    ('1', '0'): (5.12, 0.921),\n"
                    "    ('1', '1'): (5.32, 1.021),\n"
                    "}\n"
                    "sq = []\n"
                    "for row in rows:\n"
                    "    key = (str(row['y']), str(row['x']))\n"
                    "    assert row['scenario'] == 'ssp245'\n"
                    "    tas, pr = float(row['tas']), float(row['pr'])\n"
                    "    exp_tas, exp_pr = expected[key]\n"
                    "    sq.extend([(tas - exp_tas) ** 2, (pr - exp_pr) ** 2])\n"
                    "rmse = math.sqrt(sum(sq) / len(sq))\n"
                    "assert rmse < 0.08, rmse\n"
                    "meta = json.loads(meta_path.read_text(encoding='utf-8'))\n"
                    "assert meta.get('normalization_fit_on') == 'train'\n"
                    "assert meta.get('train_rows') == 12 and meta.get('test_rows') == 4\n"
                    "sub_rows = list(csv.DictReader(sub_path.open(newline='', encoding='utf-8-sig')))\n"
                    "assert len(sub_rows) == 8 and {'id', 'variable', 'prediction'} <= set(sub_rows[0])\n"
                    "manifest = json.loads(manifest_path.read_text(encoding='utf-8'))\n"
                    "assert set(manifest.get('inputs', [])) >= {'train_climate.csv', 'test_forcings.csv', 'output_contract.json'}\n"
                )
            },
            "expected_artifacts": [
                "processed/test_predictions.csv",
                "processed/metadata.json",
                "submissions/kaggle_submission.csv",
                "workflow_manifest.json",
            ],
        },
        {
            "prompt": (
                "Use filings_extract.csv and update analysis.py so answer() reconstructs the balance-sheet checks: "
                "total assets, total liabilities, equity, and whether assets equal liabilities plus equity. Run tests until they pass."
            ),
            "visible": {
                "filings_extract.csv": (
                    "line_item,amount_musd\n"
                    "cash,18\n"
                    "inventory,7\n"
                    "equipment,35\n"
                    "accounts_payable,9\n"
                    "long_term_debt,21\n"
                    "retained_earnings,30\n"
                ),
                "analysis.py": (
                    "def answer():\n"
                    "    return {\n"
                    "        'assets': 0,\n"
                    "        'liabilities': 0,\n"
                    "        'equity': 0,\n"
                    "        'balances': False,\n"
                    "    }\n"
                ),
            },
            "hidden": {
                "tests.py": (
                    "from analysis import answer\n\n"
                    "result = answer()\n"
                    "assert result['assets'] == 60\n"
                    "assert result['liabilities'] == 30\n"
                    "assert result['equity'] == 30\n"
                    "assert result['balances'] is True\n"
                )
            },
        },
        {
            "prompt": (
                "Build a compact bioinformatics differential-expression pipeline from counts.tsv, metadata.tsv, "
                "gene_map.tsv, and analysis_spec.json. Compare tumor against normal, classify each gene, write "
                "output/DE_results.tsv, output/upregulated_enrichment.tsv, output/downregulated_enrichment.tsv, "
                "and workflow_manifest.json exactly as described in output_contract.json. Run tests until they pass."
            ),
            "visible": {
                "counts.tsv": (
                    "gene_id\tnormal_1\tnormal_2\ttumor_1\ttumor_2\n"
                    "ENSG0001\t50\t52\t210\t220\n"
                    "ENSG0002\t180\t175\t45\t40\n"
                    "ENSG0003\t90\t88\t95\t93\n"
                    "ENSG0004\t30\t28\t80\t84\n"
                ),
                "metadata.tsv": "sample_id\tcondition\tbatch\nnormal_1\tnormal\tA\nnormal_2\tnormal\tB\ntumor_1\ttumor\tA\ntumor_2\ttumor\tB\n",
                "gene_map.tsv": "gene_id\tgene_symbol\nENSG0001\tBRCA1\nENSG0002\tTP53\nENSG0003\tGAPDH\nENSG0004\tERBB2\n",
                "analysis_spec.json": json.dumps(
                    {
                        "contrast": {"condition": "tumor_vs_normal"},
                        "classification_rule": {
                            "upregulated": "log2FoldChange > 1 and padj < 0.05",
                            "downregulated": "log2FoldChange < -1 and padj < 0.05",
                            "otherwise": "no significant",
                        },
                        "enrichment_library": "KEGG_2021_Human",
                    },
                    indent=2,
                ),
                "output_contract.json": json.dumps(
                    {
                        "output/DE_results.tsv": {
                            "columns": ["gene_id", "gene", "log2FoldChange", "padj", "significant"],
                            "rows": 4,
                        },
                        "output/upregulated_enrichment.tsv": {"columns": ["term", "overlap_genes", "adjusted_pvalue"]},
                        "output/downregulated_enrichment.tsv": {"columns": ["term", "overlap_genes", "adjusted_pvalue"]},
                        "workflow_manifest.json": {"required_fields": ["inputs", "outputs", "commands_or_steps"]},
                    },
                    indent=2,
                ),
                "analysis.py": (
                    "def main():\n"
                    "    raise NotImplementedError('Write the differential-expression outputs and manifest.')\n\n"
                    "if __name__ == '__main__':\n"
                    "    main()\n"
                ),
            },
            "hidden": {
                "tests.py": (
                    "import csv, json\n"
                    "from pathlib import Path\n\n"
                    "de_path = Path('output/DE_results.tsv')\n"
                    "up_path = Path('output/upregulated_enrichment.tsv')\n"
                    "down_path = Path('output/downregulated_enrichment.tsv')\n"
                    "manifest_path = Path('workflow_manifest.json')\n"
                    "for path in [de_path, up_path, down_path, manifest_path]:\n"
                    "    assert path.is_file() and path.stat().st_size > 0, f'missing {path}'\n"
                    "rows = list(csv.DictReader(de_path.open(newline='', encoding='utf-8-sig'), delimiter='\\t'))\n"
                    "assert len(rows) == 4\n"
                    "by_gene = {row['gene_id']: row for row in rows}\n"
                    "assert by_gene['ENSG0001']['gene'] == 'BRCA1'\n"
                    "assert by_gene['ENSG0002']['gene'] == 'TP53'\n"
                    "assert by_gene['ENSG0001']['significant'] == 'upregulated'\n"
                    "assert by_gene['ENSG0002']['significant'] == 'downregulated'\n"
                    "assert by_gene['ENSG0003']['significant'] == 'no significant'\n"
                    "assert float(by_gene['ENSG0001']['log2FoldChange']) > 1.0\n"
                    "assert float(by_gene['ENSG0002']['log2FoldChange']) < -1.0\n"
                    "up_terms = list(csv.DictReader(up_path.open(newline='', encoding='utf-8-sig'), delimiter='\\t'))\n"
                    "down_terms = list(csv.DictReader(down_path.open(newline='', encoding='utf-8-sig'), delimiter='\\t'))\n"
                    "assert any('BRCA1' in row.get('overlap_genes', '') for row in up_terms)\n"
                    "assert any('TP53' in row.get('overlap_genes', '') for row in down_terms)\n"
                    "manifest = json.loads(manifest_path.read_text(encoding='utf-8'))\n"
                    "assert set(manifest.get('inputs', [])) >= {'counts.tsv', 'metadata.tsv', 'gene_map.tsv', 'analysis_spec.json'}\n"
                )
            },
            "expected_artifacts": [
                "output/DE_results.tsv",
                "output/upregulated_enrichment.tsv",
                "output/downregulated_enrichment.tsv",
                "workflow_manifest.json",
            ],
        },
        {
            "prompt": (
                "Inspect experiment_runs.csv and protocol.md, update analysis.py so answer() returns the selected "
                "run, the rejection reason for excluded runs, and the normalized metric. Also create "
                "workflow_manifest.json documenting input files and commands used. Run tests until they pass."
            ),
            "visible": {
                "experiment_runs.csv": (
                    "run_id,signal,background,replicates,status\n"
                    "r1,12.0,3.0,3,complete\n"
                    "r2,18.5,4.5,2,incomplete\n"
                    "r3,17.0,5.0,4,complete\n"
                ),
                "protocol.md": (
                    "# Selection protocol\n\n"
                    "Use only complete runs with at least 3 replicates. Normalize as (signal-background)/replicates. "
                    "Select the run with the highest normalized value and document rejected runs.\n"
                ),
                "analysis.py": (
                    "def answer():\n"
                    "    return {\n"
                    "        'selected_run': '',\n"
                    "        'normalized_metric': 0.0,\n"
                    "        'rejected_runs': {},\n"
                    "    }\n"
                ),
            },
            "hidden": {
                "tests.py": (
                    "import json\n"
                    "from pathlib import Path\n"
                    "from analysis import answer\n\n"
                    "result = answer()\n"
                    "assert result['selected_run'] == 'r1'\n"
                    "assert abs(result['normalized_metric'] - 3.0) < 1e-9\n"
                    "assert result['rejected_runs'].get('r2') == 'incomplete_or_insufficient_replicates'\n"
                    "manifest = json.loads(Path('workflow_manifest.json').read_text(encoding='utf-8'))\n"
                    "assert set(manifest.get('inputs', [])) >= {'experiment_runs.csv', 'protocol.md'}\n"
                    "assert manifest.get('output') == 'analysis.answer'\n"
                )
            },
        },
    ]
    full_text = " ".join(
        [dimension.id, dimension.name, dimension.description, dimension.approach, blueprint.title, blueprint.description]
    ).lower()
    route_text = " ".join(
        [
            dimension.id,
            dimension.name,
            dimension.approach,
            " ".join(dimension.item_requirements),
            blueprint.id,
            blueprint.title,
            blueprint.description,
            blueprint.source_strategy,
            " ".join(blueprint.construction_requirements),
        ]
    ).lower()
    if "provenance" in dimension.id or "provenance" in dimension.name.lower():
        variant = variants[4]
    elif _contains_any(route_text, ("bioinformatics", "variant", "genomics", "clinical")) or (
        dimension.id == "domain_data_pipeline_execution"
        and _contains_any(
            full_text,
            (
                "bioinformatics",
                "genomics",
                "gene expression",
                "differential",
                "enrichment",
                "life-science data analysis",
                "life science data analysis",
                "staged data tables",
                "analysis contract",
                "structured result tables",
            ),
        )
    ):
        variant = variants[3]
    elif _contains_any(route_text, ("climate", "zarr", "netcdf", "scientific", "simulation", "numerical")):
        variant = variants[1]
    elif _contains_any(route_text, ("financial", "statement", "sec filing", "10-k", "balance-sheet", "balance sheet")):
        variant = variants[2]
    else:
        variant = variants[(index - 1) % len(variants)]
    expected_artifacts = list(variant.get("expected_artifacts", [])) if isinstance(variant.get("expected_artifacts"), list) else []
    if not expected_artifacts:
        expected_artifacts = ["analysis.py"]
    if "workflow_manifest.json" in str(variant["prompt"]):
        expected_artifacts.append("workflow_manifest.json")
        expected_artifacts = list(dict.fromkeys(expected_artifacts))
    return AgentTask(
        id=_task_id(dimension, blueprint, index),
        dimension_id=dimension.id,
        title=_task_title(blueprint, index),
        description=(
            "A data-analysis task that requires inspecting a local dataset, computing aggregate metrics, "
            "and encoding the result in a deterministic answer function."
        ),
        prompt=str(variant["prompt"]),
        system_prompt=_agent_system_prompt(env_type.value),
        environment=AgentEnvironmentSpec(
            type=env_type,
            visible_files=variant["visible"],
            hidden_files=variant["hidden"],
            test_command="python3 tests.py",
            max_steps=8,
            timeout=10,
            evaluation={
                "method": "hidden_tests",
                "expected_artifacts": expected_artifacts,
                "checks": [
                    {
                        "name": "hidden_tests_pass",
                        "description": "The hidden tests pass against the produced analysis code and required artifacts.",
                        "weight": 0.8,
                    },
                    {
                        "name": "inputs_used",
                        "description": "The answer is derived from the visible dataset and instructions.",
                        "weight": 0.2,
                    },
                ],
                "pass_criteria": "All hidden tests pass and required artifacts are present.",
                "partial_criteria": "Some computed fields are correct or required artifacts are partially present.",
                "fail_criteria": "The agent does not inspect the dataset or produce usable executable outputs.",
            },
            **env_kwargs,
        ),
        interaction={
            "max_turns": 8,
            "stop_condition": "Stop when the computed analysis passes hidden tests.",
        },
        scoring=AgentScoringSpec(
            method="deterministic",
            instructions="Score by hidden tests checking exact computed metrics.",
            pass_criteria="All aggregate metrics are correct and derived from the provided dataset.",
            partial_criteria="Some metrics are correct but at least one aggregation is wrong.",
            fail_criteria="The agent does not inspect or compute from the dataset.",
        ),
        challenge_effort=dimension.challenge_effort,
        tags=[dimension.id, "data_analysis", env_type.value],
    )
