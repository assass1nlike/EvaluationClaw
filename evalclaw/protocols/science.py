"""Science-domain planning and item metadata guidance."""
from __future__ import annotations

import re
from typing import Any

from ..types import BenchmarkItem

SCIENCE_METADATA_KEY = "science"
SCIENCE_SCHEMA_VERSION = "evalclaw.science.v1"

SCIENCE_KEYWORDS = (
    "science",
    "scientific",
    "physics",
    "chemistry",
    "biology",
    "biochemistry",
    "medicine",
    "medical",
    "clinical",
    "neuroscience",
    "astronomy",
    "astrophysics",
    "geology",
    "earth science",
    "climate",
    "ecology",
    "materials science",
    "genetics",
    "molecular",
    "cell biology",
    "thermodynamics",
    "mechanics",
    "electromagnetism",
    "organic chemistry",
    "experiment",
    "hypothesis",
    "lab",
    "laboratory",
    "paper",
    "abstract",
    "peer review",
    "units",
    "科学",
    "物理",
    "化学",
    "生物",
    "医学",
    "临床",
    "实验",
    "证据",
    "定量",
    "单位",
    "论文",
    "天文",
    "地质",
    "生态",
    "气候",
)

SCIENCE_NEGATIVE_PATTERNS = (
    "not science",
    "non-science",
    "no science",
    "without science",
    "不要科学",
    "非科学",
)

SCIENCE_SCHEMA: dict[str, Any] = {
    "schema_version": SCIENCE_SCHEMA_VERSION,
    "discipline": "physics | chemistry | biology | medicine | earth_science | astronomy | interdisciplinary",
    "subdomain": "short subdomain label",
    "scientific_skill": (
        "conceptual_understanding | quantitative_reasoning | experimental_design | "
        "data_interpretation | literature_reasoning | uncertainty_calibration"
    ),
    "evidence_context": "self_contained | source_grounded | provided_data | provided_paper_excerpt",
    "answer_type": "multiple_choice | exact_numeric | short_explanation | rubric_scored",
    "units": "required units when applicable, otherwise empty string",
    "assumptions": ["explicit assumptions, constants, approximations, or scope limits"],
    "safety_notes": "for medical/clinical or safety-sensitive science, evaluate reasoning only and avoid actionable advice",
}

SCIENCE_PLANNER_GUIDANCE = """\
The user is asking for science-domain evaluation. Plan dimensions around the
scientific capability being measured, not generic trivia. Choose from these
dimension families only when they fit the request:
- conceptual scientific understanding within one or more disciplines
- quantitative reasoning with units, approximations, formulas, or dimensional analysis
- experimental design, controls, variables, confounders, and causal interpretation
- data/table/figure interpretation using text-provided data unless multimodal was explicitly requested
- literature or abstract-grounded reasoning with source excerpts and evidence citation
- uncertainty calibration: recognizing underdetermined results, measurement error, and limits of evidence

For advanced or large science evaluations, prefer source-backed/imported
benchmarks when appropriate: GPQA-style graduate science QA, SciQ, PubMedQA,
MedQA, MMLU/MMLU-Pro science subsets, ChemBench, domain-specific educational
question sets, or other authoritative reproducible sources that match the
requested discipline. Do not drift into medical advice, generic IQ puzzles, or
pop-science trivia merely because a source is easy to find.

Item requirements for science dimensions should say what scientific skill is
tested, what evidence/constants/data must be provided in the prompt, how units
and assumptions are scored, and that generation workers should include
metadata.science using schema_version evalclaw.science.v1.
"""

SCIENCE_GENERATION_GUIDANCE = """\
The assigned dimension is science-domain evaluation. Generate scientifically
valid, self-contained benchmark items unless the supplied source_context provides
the needed evidence. Every science item should include metadata.science using
schema_version evalclaw.science.v1.

Science item rules:
- Do not rely on unstated specialist facts when the dimension is testing
  reasoning rather than memorized knowledge. Provide constants, equations,
  paper excerpts, tables, observations, or assumptions as needed.
- For quantitative items, include required units, enough numeric information,
  and a single unambiguous answer or rubric. Check dimensional consistency.
- For multiple_choice, include exactly one best answer, plausible distractors,
  and an answer letter that matches the rubric.
- For experimental-design items, specify hypothesis, variables, controls,
  sample/measurement constraints, and confounders clearly enough to score.
- For literature-grounded items, include a short abstract/excerpt or cite the
  provided source context; ask about evidence, limitations, or inference rather
  than unsupported claims.
- For medical/clinical science, evaluate scientific reasoning from supplied
  evidence and avoid giving patient-specific diagnosis, treatment, dosing, or
  emergency instructions.
- Do not create images, charts, or other media unless the dimension explicitly
  asks for multimodal input; text tables are fine for data interpretation.
"""


def text_requests_science(text: str) -> bool:
    """Return whether text asks for science-domain evaluation."""
    lowered = text.lower()
    if any(pattern in lowered for pattern in SCIENCE_NEGATIVE_PATTERNS):
        return False
    for keyword in SCIENCE_KEYWORDS:
        if re.search(r"[\u3400-\u9fff]", keyword):
            if keyword in lowered:
                return True
            continue
        if " " in keyword:
            if keyword in lowered:
                return True
            continue
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return True
    return False


def get_science_spec(item: BenchmarkItem) -> dict[str, Any] | None:
    spec = item.metadata.get(SCIENCE_METADATA_KEY)
    return spec if isinstance(spec, dict) else None


def science_metadata_issues(item: BenchmarkItem) -> list[str]:
    spec = get_science_spec(item)
    if not spec:
        return []
    issues: list[str] = []
    if spec.get("schema_version") != SCIENCE_SCHEMA_VERSION:
        issues.append("metadata.science.schema_version must be evalclaw.science.v1.")
    for key in ("discipline", "scientific_skill", "evidence_context", "answer_type"):
        if not str(spec.get(key) or "").strip():
            issues.append(f"metadata.science.{key} must be populated.")
    assumptions = spec.get("assumptions")
    if assumptions is not None and not isinstance(assumptions, list):
        issues.append("metadata.science.assumptions must be a list when provided.")
    return issues
