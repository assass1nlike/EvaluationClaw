"""Deterministic fallback benchmark-item generation."""
from __future__ import annotations

import uuid
from itertools import cycle

from ..protocols.multimodal import (
    MULTIMODAL_METADATA_KEY,
    MULTIMODAL_SCHEMA_VERSION,
    text_requests_multimodal,
)
from ..protocols.science import SCIENCE_METADATA_KEY, SCIENCE_SCHEMA_VERSION, text_requests_science
from ..types import BenchmarkItem, ChallengeEffort, ChoiceOption, EvalDimension, EvalSpec, TaskType


def _choice_options(values: list[object]) -> list[ChoiceOption]:
    options: list[ChoiceOption] = []
    for index, value in enumerate(values):
        option_id = chr(ord("A") + index)
        text = str(value).strip()
        for separator in (". ", ") ", ": "):
            prefix = option_id + separator
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                break
        options.append(ChoiceOption(id=option_id, text=text))
    return options


def _challenge_effort_cycle(dimension: EvalDimension) -> cycle[ChallengeEffort]:
    if not dimension.challenge_effort_distribution:
        return cycle([dimension.challenge_effort])
    distribution = dimension.challenge_effort_distribution
    expanded: list[ChallengeEffort] = []
    for challenge_effort, weight in sorted(distribution.items(), key=lambda item: item[0].value):
        expanded.extend([challenge_effort] * max(1, round(float(weight) * 10)))
    return cycle(expanded or [dimension.challenge_effort])


def _dimension_needs_multimodal(dimension: EvalDimension) -> bool:
    text = " ".join([dimension.name, dimension.description, dimension.approach, *dimension.item_requirements])
    return text_requests_multimodal(text)


def _dimension_needs_science(dimension: EvalDimension) -> bool:
    text = " ".join([dimension.name, dimension.description, dimension.approach, *dimension.item_requirements])
    return text_requests_science(text)


def _dimension_text(dimension: EvalDimension) -> str:
    return " ".join([dimension.name, dimension.description, dimension.approach, *dimension.item_requirements]).lower()


def _chart_kind(dimension: EvalDimension) -> str | None:
    text = _dimension_text(dimension)
    if not any(keyword in text for keyword in ("chart", "plot", "graph")):
        return None
    if "line" in text:
        return "line"
    if "pie" in text:
        return "pie"
    return "bar"


def has_programmatic_multimodal_fallback(dimension: EvalDimension) -> bool:
    """Return whether Evalclaw can synthesize reliable media for this dimension."""
    return _chart_kind(dimension) is not None


def _chart_svg(kind: str) -> tuple[str, str]:
    if kind == "line":
        return (
            """
<svg xmlns="http://www.w3.org/2000/svg" width="768" height="432" viewBox="0 0 768 432">
  <rect width="768" height="432" fill="#ffffff"/>
  <text x="70" y="54" font-family="Arial" font-size="28" fill="#111827">Monthly Defect Count</text>
  <line x1="90" y1="350" x2="700" y2="350" stroke="#374151" stroke-width="3"/>
  <line x1="90" y1="90" x2="90" y2="350" stroke="#374151" stroke-width="3"/>
  <polyline points="140,285 300,245 460,155 620,205" fill="none" stroke="#2563eb" stroke-width="6"/>
  <circle cx="140" cy="285" r="8" fill="#2563eb"/><text x="126" y="316" font-family="Arial" font-size="18">Jan</text><text x="132" y="276" font-family="Arial" font-size="18">5</text>
  <circle cx="300" cy="245" r="8" fill="#2563eb"/><text x="286" y="316" font-family="Arial" font-size="18">Feb</text><text x="292" y="236" font-family="Arial" font-size="18">8</text>
  <circle cx="460" cy="155" r="8" fill="#2563eb"/><text x="446" y="316" font-family="Arial" font-size="18">Mar</text><text x="447" y="146" font-family="Arial" font-size="18">14</text>
  <circle cx="620" cy="205" r="8" fill="#2563eb"/><text x="608" y="316" font-family="Arial" font-size="18">Apr</text><text x="607" y="196" font-family="Arial" font-size="18">11</text>
</svg>
""".strip(),
            "Line chart titled Monthly Defect Count: Jan 5, Feb 8, Mar 14, Apr 11.",
        )
    if kind == "pie":
        return (
            """
<svg xmlns="http://www.w3.org/2000/svg" width="768" height="432" viewBox="0 0 768 432">
  <rect width="768" height="432" fill="#ffffff"/>
  <text x="70" y="54" font-family="Arial" font-size="28" fill="#111827">Support Tickets by Product</text>
  <circle cx="250" cy="230" r="130" fill="#60a5fa"/>
  <path d="M250 230 L250 100 A130 130 0 0 1 373 272 Z" fill="#f59e0b"/>
  <path d="M250 230 L373 272 A130 130 0 0 1 250 100 Z" fill="#34d399"/>
  <rect x="470" y="150" width="28" height="28" fill="#60a5fa"/><text x="510" y="173" font-family="Arial" font-size="22">Product A: 45%</text>
  <rect x="470" y="205" width="28" height="28" fill="#f59e0b"/><text x="510" y="228" font-family="Arial" font-size="22">Product B: 30%</text>
  <rect x="470" y="260" width="28" height="28" fill="#34d399"/><text x="510" y="283" font-family="Arial" font-size="22">Product C: 25%</text>
</svg>
""".strip(),
            "Pie chart titled Support Tickets by Product: Product A 45%, Product B 30%, Product C 25%.",
        )
    return (
        """
<svg xmlns="http://www.w3.org/2000/svg" width="768" height="432" viewBox="0 0 768 432">
  <rect width="768" height="432" fill="#ffffff"/>
  <text x="70" y="54" font-family="Arial" font-size="28" fill="#111827">Quarterly Support Tickets</text>
  <line x1="90" y1="350" x2="700" y2="350" stroke="#374151" stroke-width="3"/>
  <line x1="90" y1="90" x2="90" y2="350" stroke="#374151" stroke-width="3"/>
  <rect x="145" y="206" width="78" height="144" fill="#60a5fa"/><text x="161" y="380" font-family="Arial" font-size="20">Q1</text><text x="169" y="196" font-family="Arial" font-size="20">12</text>
  <rect x="285" y="134" width="78" height="216" fill="#2563eb"/><text x="301" y="380" font-family="Arial" font-size="20">Q2</text><text x="309" y="124" font-family="Arial" font-size="20">18</text>
  <rect x="425" y="242" width="78" height="108" fill="#93c5fd"/><text x="441" y="380" font-family="Arial" font-size="20">Q3</text><text x="454" y="232" font-family="Arial" font-size="20">9</text>
  <rect x="565" y="170" width="78" height="180" fill="#3b82f6"/><text x="581" y="380" font-family="Arial" font-size="20">Q4</text><text x="589" y="160" font-family="Arial" font-size="20">15</text>
</svg>
""".strip(),
        "Bar chart titled Quarterly Support Tickets: Q1 12, Q2 18, Q3 9, Q4 15.",
    )


def _chart_question(kind: str, dimension: EvalDimension) -> tuple[str, str, list[str], str]:
    text = _dimension_text(dimension)
    asks_comparison = any(token in text for token in ("comparison", "compare", "relative", "largest", "highest", "lowest"))
    asks_single_value = any(token in text for token in ("element", "recognition", "extract", "extraction", "exact value", "reading"))
    asks_trend = any(token in text for token in ("trend", "change over time", "increase", "decrease"))
    if asks_comparison:
        asks_single_value = False
        asks_trend = False
    if kind == "line":
        if asks_comparison:
            return (
                "Inspect the attached line chart. Which has more defects, March or April, and by how many? "
                "Answer with both visible values and the difference.",
                "March has 3 more defects than April (14 vs 11).",
                ["A. March by 3", "B. April by 3", "C. March by 6", "D. They are tied"],
                (
                    "Full credit: says March/Mar is higher by 3 and cites 14 vs 11. Partial credit: "
                    "identifies March but omits either the values or the difference. No credit: wrong month or difference."
                ),
            )
        if asks_single_value:
            return (
                "Inspect the attached line chart. What is the defect count for February? "
                "Answer with the month and value, citing the visible label.",
                "Feb 8",
                ["A. Feb, 8", "B. Jan, 5", "C. Mar, 14", "D. Apr, 11"],
                (
                    "Full credit: states February/Feb has value 8 and cites the visible label. "
                    "Partial credit: gives 8 without citing February or gives February without the value. "
                    "No credit: gives another month/value or does not use chart evidence."
                ),
            )
        if asks_trend:
            return (
                "Inspect the attached line chart. Describe the trend from January through April, citing at least two visible values.",
                "Defects rise from Jan 5 to Mar 14, then fall to Apr 11.",
                ["A. Rises to Mar then falls in Apr", "B. Falls every month", "C. Stays flat", "D. Peaks in Jan"],
                (
                    "Full credit: says defects rise from Jan 5 to Mar 14 and then fall to Apr 11. "
                    "Partial credit: describes the rise/fall pattern without enough values. No credit: gives the wrong trend."
                ),
            )
        return (
            "Inspect the attached line chart. Which month has the highest defect count? "
            "Answer with the month and value, citing the visible label.",
            "Mar",
            ["A. Mar, 14", "B. Apr, 11", "C. Feb, 8", "D. Jan, 5"],
            (
                "Full credit: identifies March/Mar as the highest point and cites value 14. "
                "Partial credit: identifies March without the value or gives the correct trend but not the exact peak. "
                "No credit: names another month or does not use chart evidence."
            ),
        )
    if kind == "pie":
        if asks_comparison:
            return (
                "Inspect the attached pie chart. Compare Product A and Product B. Which has the larger share, "
                "and by how many percentage points? Cite both visible labels.",
                "Product A is larger by 15 percentage points (45% vs 30%).",
                ["A. Product A by 15 points", "B. Product B by 15 points", "C. Product A by 20 points", "D. They are tied"],
                (
                    "Full credit: says Product A is larger by 15 percentage points and cites 45% vs 30%. "
                    "Partial credit: identifies Product A without the exact difference. No credit: wrong product or difference."
                ),
            )
        if asks_single_value:
            return (
                "Inspect the attached pie chart. What percentage is shown for Product B? "
                "Answer with the product and percentage, citing the visible label.",
                "Product B 30%",
                ["A. Product B, 30%", "B. Product A, 45%", "C. Product C, 25%", "D. Product B, 25%"],
                (
                    "Full credit: states Product B is 30% and cites the visible label. Partial credit: "
                    "states 30% without Product B or Product B without the value. No credit: gives another value."
                ),
            )
        return (
            "Inspect the attached pie chart. Which product has the largest share of support tickets? "
            "Answer with the product and percentage, citing the visible label.",
            "Product A",
            ["A. Product A, 45%", "B. Product B, 30%", "C. Product C, 25%", "D. Product B and C tie"],
            (
                "Full credit: identifies Product A as largest and cites 45%. Partial credit: identifies Product A "
                "without the percentage. No credit: chooses another product or does not use chart evidence."
            ),
        )
    if asks_single_value:
        return (
            "Inspect the attached bar chart. What is the support ticket count for Q3? "
            "Answer with the quarter and value, citing the visible label.",
            "Q3 9",
            ["A. Q3, 9", "B. Q1, 12", "C. Q2, 18", "D. Q4, 15"],
            (
                "Full credit: states Q3 has value 9 and cites the visible label. Partial credit: gives "
                "9 without Q3 or Q3 without the value. No credit: gives another quarter/value."
            ),
        )
    if asks_trend:
        return (
            "Inspect the attached bar chart. Summarize how support ticket counts change across Q1 to Q4, citing at least two visible values.",
            "Counts rise from Q1 12 to Q2 18, drop to Q3 9, then rise to Q4 15.",
            ["A. Up, down, then up", "B. Down every quarter", "C. Flat across all quarters", "D. Up every quarter"],
            (
                "Full credit: describes the Q1 12 -> Q2 18 rise, Q3 9 drop, and Q4 15 rebound. "
                "Partial credit: gives the broad up/down/up pattern without enough values. No credit: wrong trend."
            ),
        )
    if asks_comparison:
        return (
            "Inspect the attached bar chart. Compare Q2 and Q4. Which quarter has more support tickets, "
            "and by how many? Cite both visible labels.",
            "Q2 has 3 more tickets than Q4 (18 vs 15).",
            ["A. Q2 by 3", "B. Q4 by 3", "C. Q2 by 9", "D. They are tied"],
            (
                "Full credit: says Q2 is higher by 3 and cites 18 vs 15. Partial credit: identifies Q2 "
                "without the exact difference. No credit: wrong quarter or difference."
            ),
        )
    return (
        "Inspect the attached bar chart. Which quarter has the highest support ticket count? "
        "Answer with the quarter and value, citing the visible label.",
        "Q2",
        ["A. Q2, 18", "B. Q4, 15", "C. Q1, 12", "D. Q3, 9"],
        (
            "Full credit: identifies Q2 as the highest quarter and cites value 18. Partial credit: identifies Q2 "
            "without the value. No credit: chooses another quarter or does not use chart evidence."
        ),
    )


def _chart_multiple_choice_prompt(prompt: str) -> str:
    """Adapt an open chart prompt into a non-contradictory multiple-choice prompt."""
    for marker in (" Answer with ", " Cite "):
        index = prompt.find(marker)
        if index >= 0:
            prompt = prompt[:index].rstrip()
    if prompt and prompt[-1] not in ".?!":
        prompt += "."
    return prompt + "\nChoose the best option and answer with the letter only."


def _placeholder_multimodal_asset(dimension: EvalDimension, index: int) -> dict[str, str]:
    import base64
    import html

    chart_kind = _chart_kind(dimension)
    if chart_kind:
        svg, alt_text = _chart_svg(chart_kind)
        caption = alt_text
    else:
        label = html.escape(f"{dimension.name} #{index + 1}")
        subtitle = html.escape(dimension.description[:80] or "Multimodal evaluation asset")
        svg = f"""
<svg xmlns="http://www.w3.org/2000/svg" width="768" height="432" viewBox="0 0 768 432">
  <rect width="768" height="432" fill="#f7f7fb"/>
  <rect x="28" y="28" width="712" height="376" rx="20" fill="#ffffff" stroke="#2f3a4a" stroke-width="4"/>
  <text x="52" y="86" font-family="Arial, Helvetica, sans-serif" font-size="30" fill="#1f2937">{label}</text>
  <text x="52" y="126" font-family="Arial, Helvetica, sans-serif" font-size="20" fill="#4b5563">{subtitle}</text>
  <rect x="52" y="166" width="172" height="150" fill="#93c5fd" rx="10"/>
  <rect x="244" y="198" width="146" height="118" fill="#fca5a5" rx="10"/>
  <rect x="410" y="174" width="140" height="142" fill="#86efac" rx="10"/>
  <rect x="570" y="216" width="126" height="100" fill="#fde68a" rx="10"/>
  <text x="52" y="362" font-family="Arial, Helvetica, sans-serif" font-size="18" fill="#374151">
    EvaluationClaw multimodal fallback asset
  </text>
</svg>
""".strip()
        alt_text = subtitle
        caption = f"Fallback multimodal asset for {dimension.name}"
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {
        "id": f"image_{index + 1}",
        "kind": "image",
        "uri": f"data:image/svg+xml;base64,{data}",
        "mime_type": "image/svg+xml",
        "caption": caption,
        "alt_text": alt_text,
    }


def _multimodal_metadata_for_item(dimension: EvalDimension, index: int, prompt: str) -> dict[str, object]:
    asset = _placeholder_multimodal_asset(dimension, index)
    return {
        "schema_version": MULTIMODAL_SCHEMA_VERSION,
        "modalities": ["image"],
        "assets": [asset],
        "content": [
            {"type": "text", "text": prompt},
            {"type": "asset", "asset_id": asset["id"], "detail": "high"},
        ],
        "scoring": {
            "method": "judge_score",
            "rubric": "Score the response using the visual evidence in the attached image.",
        },
    }


def attach_multimodal_metadata_if_needed(
    item: BenchmarkItem,
    dimension: EvalDimension,
    index: int,
) -> BenchmarkItem:
    if _dimension_needs_multimodal(dimension) and MULTIMODAL_METADATA_KEY not in item.metadata:
        item.metadata[MULTIMODAL_METADATA_KEY] = _multimodal_metadata_for_item(dimension, index, item.prompt)
    multimodal = item.metadata.get(MULTIMODAL_METADATA_KEY)
    if isinstance(multimodal, dict) and item.rubric:
        scoring = multimodal.get("scoring")
        if isinstance(scoring, dict):
            scoring["rubric"] = item.rubric
    return item


def _science_metadata(
    *,
    discipline: str,
    subdomain: str,
    scientific_skill: str,
    evidence_context: str,
    answer_type: str,
    units: str = "",
    assumptions: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": SCIENCE_SCHEMA_VERSION,
        "discipline": discipline,
        "subdomain": subdomain,
        "scientific_skill": scientific_skill,
        "evidence_context": evidence_context,
        "answer_type": answer_type,
        "units": units,
        "assumptions": assumptions or [],
        "safety_notes": "Evaluate scientific reasoning from the supplied evidence; do not provide actionable advice.",
    }


def _science_fallback_item(
    dimension: EvalDimension,
    task_type: TaskType,
    challenge_effort: ChallengeEffort,
    idx: int,
) -> BenchmarkItem:
    text = _dimension_text(dimension)
    discipline = "interdisciplinary"
    if "physics" in text or "quantitative" in text or "unit" in text:
        discipline = "physics"
    elif "chem" in text:
        discipline = "chemistry"
    elif any(token in text for token in ("bio", "genetic", "cell", "ecology")):
        discipline = "biology"
    elif any(token in text for token in ("medical", "medicine", "clinical", "pubmed")):
        discipline = "medicine"

    contexts = [
        "a classroom mechanics demonstration",
        "a wet-lab methods comparison",
        "a greenhouse pilot study",
        "a materials characterization report",
        "an ecology field notebook",
        "an astronomy observation log",
        "a chemistry teaching lab",
        "a cell-biology screening assay",
        "an ocean-science mesocosm",
        "a reproducibility review meeting",
    ]
    evidence_forms = [
        "a short numeric setup",
        "a two-condition comparison",
        "a compact study excerpt",
        "an observation with one omitted mechanism",
        "a result with a small sample",
        "a controlled-variable critique",
        "a units-sensitive calculation",
        "a causality-versus-association judgment",
        "a confounder identification task",
        "a cautious inference task",
    ]
    pitfalls = [
        "confusing acceleration with final speed",
        "ignoring units",
        "overstating a causal claim",
        "missing a changed control variable",
        "treating a small study as definitive",
        "assuming an unmeasured mechanism",
        "generalizing beyond the stated evidence",
        "choosing an answer with the right direction but wrong magnitude",
        "forgetting that correlation does not establish mechanism",
        "dropping an explicit experimental assumption",
    ]
    context = contexts[idx % len(contexts)]
    evidence_form = evidence_forms[(idx // len(contexts)) % len(evidence_forms)]
    pitfall = pitfalls[(idx // (len(contexts) * len(evidence_forms))) % len(pitfalls)]

    if idx % 3 == 0:
        mass = 1.0 + (idx % 7)
        force = 4.0 + ((idx * 3) % 11)
        time_s = 2.0 + ((idx * 5) % 7)
        speed = force / mass * time_s
        distractor_1 = speed / 2
        distractor_2 = speed + mass
        distractor_3 = speed * 2 + 1
        case = {
            "skill": "quantitative_reasoning",
            "subdomain": "mechanics",
            "prompt": (
                f"A {mass:.1f} kg cart starts from rest and is pushed by a constant {force:.1f} N "
                f"horizontal force for {time_s:.1f} s on a frictionless track. What is the cart's "
                "speed at the end of the push? Use F = ma and answer with units."
            ),
            "answer": f"{speed:.2f} m/s",
            "choices": [
                f"A. {distractor_1:.2f} m/s",
                f"B. {distractor_2:.2f} m/s",
                f"C. {speed:.2f} m/s",
                f"D. {distractor_3:.2f} m/s",
            ],
            "correct": "C",
            "rubric": (
                f"Full credit: computes a = {force:.1f}/{mass:.1f} = {force / mass:.2f} m/s^2 "
                f"and v = at = {speed:.2f} m/s with units. Partial credit for correct method "
                "with arithmetic or unit error."
            ),
            "units": "m/s",
            "assumptions": ["frictionless track", "constant force", "starts from rest"],
        }
    elif idx % 3 == 1:
        systems = [
            ("buffer", "enzyme activity", "temperature", "test both buffers at the same temperature"),
            ("light color", "algal growth", "nutrient concentration", "use equal nutrient concentration in all tanks"),
            ("soil additive", "seed germination", "watering frequency", "water all groups on the same schedule"),
            ("catalyst", "reaction rate", "reactant concentration", "hold reactant concentration constant"),
            ("incubator setting", "bacterial growth", "starting cell density", "start all cultures at the same density"),
            ("mineral supplement", "bone-cell marker expression", "culture passage number", "compare cultures at the same passage"),
            ("cooling protocol", "crystal formation", "solution pH", "hold pH constant across all groups"),
        ]
        treatment, outcome, confounder, control = systems[(idx // 3) % len(systems)]
        case = {
            "skill": "experimental_design",
            "subdomain": "controlled experiment design",
            "prompt": (
                f"A lab claims a new {treatment} improves {outcome}. They tested one group with "
                f"the new {treatment} while also changing {confounder}, then compared it with an "
                f"old-condition group. Identify the main confounder and propose one control that "
                "would make the comparison more valid."
            ),
            "answer": f"{confounder} is confounded with {treatment}; {control}.",
            "choices": [
                f"A. {confounder.capitalize()} is confounded with {treatment}; {control}",
                "B. The result proves the treatment directly caused the outcome",
                "C. The control group should be removed because it adds noise",
                "D. The measured outcome is irrelevant and should not be recorded",
            ],
            "correct": "A",
            "rubric": (
                f"Full credit: identifies {confounder} as the confounder and proposes an equivalent "
                "controlled comparison. Partial credit for naming a relevant control without explaining "
                "why it matters."
            ),
            "units": "",
            "assumptions": [f"{outcome} may depend on {confounder}"],
        }
    else:
        studies = [
            ("greenhouse experiment", "fertilizer X", "plants", "grew 12% taller", "leaf nitrogen did not differ", 8),
            ("cell-culture assay", "compound Q", "cells", "showed 18% lower viability", "apoptosis markers were unchanged", 6),
            ("field survey", "habitat restoration", "bird counts", "were 9% higher", "nest success was not measured", 12),
            ("materials test", "coating M", "samples", "resisted abrasion 15% longer", "humidity was not varied", 5),
            ("microbiome study", "diet A", "mice", "had 20% more taxon R", "body mass did not differ", 10),
            ("astronomy observation", "filter set Z", "galaxy candidates", "appeared 11% brighter", "redshift uncertainty remained high", 7),
            ("ocean chemistry mesocosm", "alkalinity treatment", "plankton communities", "had 14% higher calcification", "temperature was held constant", 9),
        ]
        setting, intervention, subject, result, limitation, sample_size = studies[(idx // 3) % len(studies)]
        case = {
            "skill": "literature_reasoning",
            "subdomain": "evidence interpretation",
            "prompt": (
                f"Study excerpt: In a randomized {setting}, {subject} receiving {intervention} {result} "
                f"than controls after six weeks, but {limitation} and the sample size was {sample_size} "
                "per group. What is the most cautious interpretation?"
            ),
            "answer": (
                f"{intervention} is associated with the reported outcome in this small study, but "
                "mechanism and generality remain uncertain."
            ),
            "choices": [
                f"A. {intervention} conclusively works by the unmeasured mechanism in all settings",
                "B. The result is an association in this small study, with mechanism and generality uncertain",
                "C. The control group proves there is no possible effect",
                "D. The result establishes long-term performance in every environment",
            ],
            "correct": "B",
            "rubric": (
                "Full credit: states the observed association while preserving uncertainty about mechanism, "
                "sample size, and generalization. No credit for unsupported causal or broad claims."
            ),
            "units": "",
            "assumptions": ["small study results may not generalize without replication"],
        }
    answer_type = "choice" if task_type == TaskType.choice else "short_explanation"
    metadata = {
        SCIENCE_METADATA_KEY: _science_metadata(
            discipline=discipline,
            subdomain=str(case["subdomain"]),
            scientific_skill=str(case["skill"]),
            evidence_context="self_contained",
            answer_type=answer_type,
            units=str(case["units"]),
            assumptions=[str(x) for x in case["assumptions"]],
        )
    }
    prompt = (
        f"Science dimension: {dimension.name}. Science evaluation case {idx + 1} "
        f"({challenge_effort.value}). Context: this item uses {context}, framed as {evidence_form}; "
        f"the main distractor should test {pitfall}. {case['prompt']}"
    )
    if task_type == TaskType.choice:
        return BenchmarkItem(
            id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
            dimension_id=dimension.id,
            task_type=TaskType.choice,
            prompt=prompt + "\nChoose the best option and answer with the letter only.",
            choices=_choice_options(list(case["choices"])),
            correct_choice_ids=[str(case["correct"])],
            rubric=f"Multiple-choice scoring: full credit for answer {case['correct']}. {case['rubric']}",
            challenge_effort=challenge_effort,
            metadata=metadata,
        )
    return BenchmarkItem(
        id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
        dimension_id=dimension.id,
        task_type=TaskType.fill_blank if task_type == TaskType.fill_blank else TaskType.generation,
        prompt=prompt,
        expected_text=str(case["answer"]) if task_type == TaskType.fill_blank else None,
        rubric=str(case["rubric"]),
        challenge_effort=challenge_effort,
        metadata=metadata,
    )


def fallback_items(spec: EvalSpec, dimension: EvalDimension, count: int) -> list[BenchmarkItem]:
    tasks = cycle(dimension.task_types or spec.task_types or [TaskType.generation])
    challenge_efforts = _challenge_effort_cycle(dimension)
    items: list[BenchmarkItem] = []
    scenario_domains = [
        "a Python package that recently split its configuration across pyproject.toml and setup.cfg",
        "a TypeScript service whose failing tests come from a stale generated client",
        "a data pipeline where one platform uses POSIX paths and another uses Windows paths",
        "a CLI tool whose behavior changes when an optional dependency is missing",
        "a web backend where a small schema migration affects two request handlers",
        "a notebook-to-script export flow that silently changes relative imports",
        "a Dockerized test runner with cached layers and a missing environment variable",
        "a plugin system where two extensions register the same command name",
        "a monorepo package that shares helpers between unit tests and integration tests",
        "a release script that must preserve compatibility with older lockfiles",
    ]
    observed_failures = [
        "one test fails only after the full suite has run",
        "the reproduction command passes locally but fails in a clean environment",
        "the stack trace points at a wrapper rather than the real source of the bug",
        "the model must inspect more than one file before proposing a patch",
        "the expected behavior is implied by tests rather than fully stated",
        "a tempting dependency upgrade would mask the underlying issue",
        "a generated artifact should not be hand-edited",
        "the obvious one-line patch breaks an edge case",
        "the task requires distinguishing setup failure from product failure",
        "the final answer should report exactly what changed and what remains unverified",
    ]
    constraints = [
        "keep the public API unchanged",
        "avoid network access during tests",
        "preserve cross-platform behavior",
        "make the smallest coherent code change",
        "add or update a focused regression test",
        "do not rewrite unrelated modules",
        "explain any environment assumption explicitly",
        "prefer deterministic validation over manual inspection",
        "treat logs as evidence but not as the sole source of truth",
        "separate diagnosis from speculative remediation",
    ]
    requested_outputs = [
        "a patch plan with the likely root cause",
        "a concise diagnosis and the next command to run",
        "a final engineering note after tests pass",
        "a risk assessment for the proposed fix",
        "a comparison between two plausible fixes",
        "a minimal test case that would catch the bug",
        "a decision on whether to edit code or environment configuration",
        "a structured summary of files that need inspection",
        "a calibrated response when the evidence is incomplete",
        "a tool-use sequence that avoids reading hidden test data",
    ]
    focus_areas = [
        "normal path behavior",
        "boundary-condition handling",
        "ambiguous input clarification",
        "cross-file consistency",
        "dependency or environment constraints",
        "test failure diagnosis",
        "incremental revision after feedback",
        "tool-result interpretation",
        "concise uncertainty handling",
        "irrelevant-context filtering",
    ]
    seed = int(uuid.uuid4().hex[:8], 16)
    for idx in range(count):
        task_type = next(tasks)
        challenge_effort = next(challenge_efforts)
        variant_id = uuid.uuid4().hex[:8]
        domain_count = len(scenario_domains)
        failure_count = len(observed_failures)
        constraint_count = len(constraints)
        focus = focus_areas[(seed + idx) % len(focus_areas)]
        domain = scenario_domains[(seed + idx) % domain_count]
        failure = observed_failures[((seed // domain_count) + (idx // domain_count)) % failure_count]
        constraint = constraints[
            ((seed // (domain_count * failure_count)) + (idx // (domain_count * failure_count))) % constraint_count
        ]
        requested_output = requested_outputs[
            (
                (seed // (domain_count * failure_count * constraint_count))
                + (idx // (domain_count * failure_count * constraint_count))
            )
            % len(requested_outputs)
        ]
        base = (
            f"Evaluation dimension: {dimension.name}.\n"
            f"Dimension intent: {dimension.description or dimension.approach}.\n"
            f"Case {idx + 1} ({challenge_effort.value}, {focus}, {variant_id}): The target is {domain}. "
            f"In this case, {failure}; the response must {constraint}. Ask for {requested_output} "
            "and judge whether the model stays aligned with the engineering evidence.\n"
        )
        chart_kind = _chart_kind(dimension)
        if _dimension_needs_science(dimension):
            item = _science_fallback_item(dimension, task_type, challenge_effort, idx + seed % 997)
        elif chart_kind and task_type == TaskType.choice:
            prompt, expected, choices, _ = _chart_question(chart_kind, dimension)
            item = BenchmarkItem(
                id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                dimension_id=dimension.id,
                task_type=TaskType.choice,
                prompt=_chart_multiple_choice_prompt(prompt),
                choices=_choice_options(choices),
                correct_choice_ids=["A"],
                rubric=(
                    f"Multiple-choice scoring: full credit for answer A, which matches the "
                    f"chart-supported answer ({expected}). No credit for B, C, D, or non-choice output."
                ),
                challenge_effort=challenge_effort,
            )
        elif chart_kind:
            prompt, expected, _, rubric = _chart_question(chart_kind, dimension)
            item = BenchmarkItem(
                id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt=prompt,
                rubric=rubric,
                challenge_effort=challenge_effort,
            )
        elif task_type == TaskType.choice:
            item = BenchmarkItem(
                id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                dimension_id=dimension.id,
                task_type=task_type,
                prompt=(
                    base
                    + "Which model behavior best satisfies this evaluation case? "
                    "Choose the best answer and respond with the letter only."
                ),
                choices=_choice_options([
                    "A. The response fully satisfies the dimension",
                    "B. The response partially satisfies the dimension",
                    "C. The response avoids the requested behavior",
                    "D. The response is irrelevant",
                ]),
                correct_choice_ids=["A"],
                rubric=(
                    "Multiple-choice scoring: full credit for answer A. No credit for B, C, D, "
                    "or a non-choice response. The item is a local fallback smoke-test placeholder "
                    "whose purpose is to preserve schema, scoring, and coverage mechanics."
                ),
                challenge_effort=challenge_effort,
            )
        elif task_type == TaskType.generation:
            item = BenchmarkItem(
                id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt=base + "Answer the user request as well as possible.",
                rubric=(
                    "Score 5 for a correct, complete, well-calibrated response aligned with the dimension; "
                    "3 for a partially correct response with material omissions; 1 for an incorrect, "
                    "unsupported, or non-responsive answer."
                ),
                challenge_effort=challenge_effort,
            )
        elif task_type == TaskType.agent:
            item = _agent_fallback_item(spec, dimension, challenge_effort, base)
        elif task_type == TaskType.multi_turn:
            item = _multi_turn_fallback_item(dimension, challenge_effort, base)
        else:
            item = BenchmarkItem(
                id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt=(
                    base
                    + "Produce the requested engineering response. Be specific about evidence, assumptions, "
                    "and validation steps."
                ),
                rubric=(
                    "Score 5 for a complete, correct, well-calibrated answer; 3 for a partially "
                    "correct answer with omissions; 1 for incorrect, evasive, or unsupported output."
                ),
                challenge_effort=challenge_effort,
            )
        items.append(attach_multimodal_metadata_if_needed(item, dimension, len(items)))
    return items


def _agent_fallback_item(
    spec: EvalSpec,
    dimension: EvalDimension,
    challenge_effort: ChallengeEffort,
    base: str,
) -> BenchmarkItem:
    agent_text = f"{spec.objective} {dimension.name} {dimension.description} {dimension.approach}".lower()
    if any(keyword in agent_text for keyword in ("code", "coding", "program", "debug", "python")):
        return BenchmarkItem(
            id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
            dimension_id=dimension.id,
            task_type=TaskType.agent,
            prompt=(
                base
                + "Use the code_sandbox tools to implement max_pair_sum(nums) in solution.py. "
                "Run tests, inspect failures, and revise until tests pass."
            ),
            rubric=(
                "Deterministic environment score: 1.0 when the hidden Python tests pass, "
                "0.25 after at least one failing test run, 0.0 if tests are never run."
            ),
            challenge_effort=challenge_effort,
            metadata={
                "task_agent": {
                    "schema_version": "evalclaw.task_agent.v1",
                    "agent_role": "target_agent_executor",
                    "system_prompt": (
                        "You are the target model acting as a coding agent in an EvaluationClaw "
                        "code_sandbox task. Use exactly one JSON tool action per turn. Inspect files, "
                        "write complete file contents, run tests, and revise until the tests pass. "
                        "Do not invent tools or reveal hidden test contents."
                    ),
                    "initial_content": {
                        "scenario": "Implement the requested Python function in the visible repository.",
                        "files": {"solution.py": "def max_pair_sum(nums):\n    pass\n"},
                    },
                    "interaction": {
                        "max_turns": 8,
                        "stop_condition": "Stop when hidden tests pass or the environment step limit is reached.",
                    },
                    "scoring": {
                        "method": "deterministic",
                        "pass_fail": {
                            "pass": "Hidden tests pass.",
                            "partial": "The agent runs tests but the final implementation still fails.",
                            "fail": "The agent never reaches a meaningful test run or cannot modify the code.",
                        },
                    },
                    "execution": {"environment_type": "code_sandbox"},
                },
                "agent_env": {
                    "type": "code_sandbox",
                    "visible_files": {"solution.py": "def max_pair_sum(nums):\n    pass\n"},
                    "hidden_files": {
                        "tests.py": (
                            "from solution import max_pair_sum\n\n"
                            "assert max_pair_sum([1, 2, 3, 4]) == 7\n"
                            "assert max_pair_sum([-5, -2, -3]) == -5\n"
                            "assert max_pair_sum([10, 10, 1]) == 20\n"
                        )
                    },
                    "test_command": "python3 tests.py",
                    "max_steps": 8,
                },
            },
        )
    return BenchmarkItem(
        id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
        dimension_id=dimension.id,
        task_type=TaskType.agent,
        prompt=(
            base
            + "Use the simulated workspace tools to place the blue_notebook and charged_tablet "
            "in the outgoing bin. Inspect items when needed and finish within the step limit."
        ),
        rubric=(
            "Deterministic environment score: 1.0 if all required items and no wrong items are "
            "placed in the outgoing bin, partial credit for required items placed, penalties for invalid actions."
        ),
        challenge_effort=challenge_effort,
        metadata={
            "task_agent": {
                "schema_version": "evalclaw.task_agent.v1",
                "agent_role": "target_agent_executor",
                "system_prompt": (
                    "You are the target model acting as an agent in an EvaluationClaw simulated "
                    "workspace. Use exactly one JSON action per turn. Read observations carefully, "
                    "inspect ambiguous items before taking them, and finish only after the goal is complete."
                ),
                "initial_content": {
                    "scenario": "Move only the required items into the outgoing bin in the simulated workspace.",
                },
                "interaction": {
                    "max_turns": 8,
                    "stop_condition": "Stop when required items are in the outgoing bin or the step limit is reached.",
                },
                "scoring": {
                    "method": "deterministic",
                    "pass_fail": {
                        "pass": "All required items and no wrong items are placed in the outgoing bin.",
                        "partial": "Some required items are placed, with penalties for wrong or invalid actions.",
                        "fail": "No required item is correctly placed.",
                    },
                },
                "execution": {"environment_type": "workspace"},
            },
            "agent_env": {
                "type": "workspace",
                "start_room": "office",
                "rooms": {
                    "office": ["blue_notebook", "red_notebook"],
                    "lab": ["charged_tablet", "dead_tablet"],
                    "mailroom": [],
                },
                "item_descriptions": {
                    "blue_notebook": "A blue notebook labeled project plan.",
                    "red_notebook": "A red notebook labeled old draft.",
                    "charged_tablet": "A tablet showing 100% battery.",
                    "dead_tablet": "A tablet with an empty battery icon.",
                },
                "goal": {"outgoing_bin": ["blue_notebook", "charged_tablet"]},
                "max_steps": 8,
            },
        },
    )


def _multi_turn_fallback_item(
    dimension: EvalDimension,
    challenge_effort: ChallengeEffort,
    base: str,
) -> BenchmarkItem:
    return BenchmarkItem(
        id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
        dimension_id=dimension.id,
        task_type=TaskType.multi_turn,
        prompt=base + "Respond to the user's initial request while staying consistent across later corrections.",
        rubric=(
            "Score the full dialogue. 5 means the model answers the initial request, incorporates "
            "follow-up corrections without contradiction, and maintains the required tone. 3 means "
            "partially correct handling with one important missed correction. 1 means the model ignores "
            "the follow-up or becomes inconsistent."
        ),
        challenge_effort=challenge_effort,
        metadata={
            "task_agent": {
                "schema_version": "evalclaw.task_agent.v1",
                "agent_role": "dialogue_simulator",
                "system_prompt": (
                    "You are a task-specific user simulator for an EvaluationClaw multi-turn evaluation. "
                    "Your job is to produce concise follow-up user turns that test whether the target "
                    "model remains consistent, incorporates corrections, and satisfies the assigned "
                    "dimension. Return JSON only when asked for the next turn."
                ),
                "initial_content": {
                    "scenario": f"Evaluate the target model on {dimension.name}: {dimension.description}",
                },
                "interaction": {
                    "max_turns": 2,
                    "followup_instruction": (
                        "Ask one correction or constraint-tightening follow-up, then stop once the "
                        "target has had a chance to revise."
                    ),
                    "stop_condition": "Stop after the target responds to a meaningful correction.",
                },
                "scoring": {
                    "method": "agent_judge",
                    "instructions": "Score the entire transcript for correctness, consistency, and follow-up handling.",
                    "levels": {
                        "5": "Fully satisfies the initial request and all follow-up constraints.",
                        "3": "Partially satisfies the task but misses or weakly handles one follow-up constraint.",
                        "1": "Ignores the follow-up, contradicts earlier context, or fails the main request.",
                    },
                },
                "execution": {"interaction_type": "multi_turn"},
            }
        },
    )
