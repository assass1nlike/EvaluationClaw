#!/usr/bin/env python3
"""
Enhanced Task README Generation (Step 1)

This script generates task specifications (README.md files) with enhanced
guidance including verification patterns, real data requirements, and
anti-gaming techniques.

Usage:
    python main_any_app_enhanced.py \
        --software_name "Chrome Browser" \
        --env_folder "benchmarks/cua_world/environments/chrome_env_all" \
        --max_questions 100
"""

import os
import sys
import json
import argparse
import pickle
import random
import re
from typing import List, Optional
from collections import Counter
from tqdm import tqdm

# Add parent directory to path for imports
# (path manipulation removed: package uses relative imports)

from .examples_bank import (
    select_curated_examples,
    format_examples_for_readme_prompt,
    get_domain_for_software,
    get_available_tasks_for_env,
    get_seed_tasks_for_env,
    HIGH_QUALITY_EXAMPLES,
)
from .prompt_components import (
    assemble_task_generation_prompt,
    TASK_README_OUTPUT_FORMAT,
)
from .utils_enhanced import (
    EnhancedAnthropicLLM,
    GeminiLLM,
    create_llm,
    GenerationProgress,
    extract_task_name_from_response,
    get_project_root,
)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Enhanced Task README Generation')

    # Required arguments
    parser.add_argument('--software_name', type=str, required=True,
                        help='Name of the target software (e.g., "Chrome Browser")')
    parser.add_argument('--env_folder', type=str, required=True,
                        help='Path to environment folder')

    # Optional arguments
    parser.add_argument('--max_questions', type=int, default=100,
                        help='Maximum number of tasks to generate')
    parser.add_argument('--max_examples', type=int, default=10,
                        help='Number of examples to show in prompt')
    parser.add_argument('--model', type=str, default='claude-sonnet-4-20250514',
                        help='Model to use')
    parser.add_argument('--resume', type=bool, default=True,
                        help='Resume from last checkpoint')
    parser.add_argument('--output_dir', type=str, default=None,
                        help='Output directory for pickles')
    parser.add_argument('--temperature', type=float, default=1.0,
                        help='Sampling temperature')
    parser.add_argument('--max_thinking_tokens', type=int, default=16384,
                        help='Max thinking tokens for extended thinking')
    parser.add_argument('--compact_mode', type=bool, default=False,
                        help='Use compact prompt mode to save tokens')
    parser.add_argument('--difficulty', type=str, default=None,
                        help='Filter same-env examples by difficulty (e.g., "easy", "very easy,easy")')
    parser.add_argument('--previous_pkl', type=str, default=None,
                        help='Path to a questions pkl from a previous run (e.g. Opus batch). '
                             'Task names in it are added to the deduplication list so this run '
                             'does not repeat them. Does not affect the resume checkpoint.')
    parser.add_argument('--include_same_env', type=int, default=5,
                        help='Number of same-env seed task examples to include (default: 5). '
                             'Set to 0 to disable same-env examples (for ablation).')
    parser.add_argument('--avoid_existing_tasks', type=bool, default=True,
                        help='Add all existing task directory names in env_folder/tasks to the dedupe list.')
    parser.add_argument('--osworld_profile_path', type=str, default=None,
                        help='Optional path to OSWorld-style profile JSON used to steer task distribution.')
    parser.add_argument('--osworld_profile_key', type=str, default=None,
                        help='Profile key inside osworld_profile_path. Defaults to environment folder basename.')
    parser.add_argument('--osworld_target_total', type=int, default=None,
                        help='Final target total including existing env tasks. Used to compensate category quotas.')

    return parser.parse_args()


def get_output_prefix(args) -> str:
    """Generate output file prefix based on arguments."""
    model_name = args.model.replace('/', '-')
    software_name = args.software_name.replace(' ', '_')
    return f"enhanced_{model_name}_{software_name}"


def expand_dedup_task_names(task_names: List[str]) -> List[str]:
    """Include both full task ids and base names to prevent @2 near-duplicates."""
    expanded = []
    seen = set()
    for name in task_names:
        if not name:
            continue
        candidates = [name]
        if "@" in name:
            candidates.append(name.split("@", 1)[0])
        for candidate in candidates:
            if candidate not in seen:
                expanded.append(candidate)
                seen.add(candidate)
    return expanded


def _format_osworld_profile(profile: dict) -> str:
    """Format an OSWorld distribution profile for prompt injection."""
    lines = [
        "## OSWorld-Style Distribution Profile",
        "",
        profile.get("summary", "").strip(),
        "",
        "### Distribution Goal",
        profile.get("distribution_goal", "").strip(),
        "",
        "### Current Local Strengths To Preserve",
    ]
    for item in profile.get("current_strengths", []):
        lines.append(f"- {item}")
    lines.extend(["", "### Shift Needed For This Expansion"])
    for item in profile.get("desired_shift", []):
        lines.append(f"- {item}")
    lines.extend(["", "### Target Categories"])
    for category in profile.get("categories", []):
        name = category.get("name", "Unnamed category")
        weight = category.get("weight", "")
        difficulty = category.get("difficulty", "")
        examples = ", ".join(category.get("examples", []))
        avoid = ", ".join(category.get("avoid", []))
        lines.append(f"- {name} ({weight}; target difficulty: {difficulty})")
        if examples:
            lines.append(f"  Examples: {examples}")
        if avoid:
            lines.append(f"  Avoid overdoing: {avoid}")
    lines.extend(["", "### Prompting Rules"])
    for item in profile.get("rules", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def load_osworld_profile(args, env_name: str) -> tuple[Optional[str], Optional[dict]]:
    """Load the optional OSWorld-style task profile."""
    if not args.osworld_profile_path:
        return None, None
    profile_path = os.path.abspath(args.osworld_profile_path)
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            profiles = json.load(f)
    except Exception as e:
        print(f"    WARNING: Could not load OSWorld profile '{profile_path}': {e}")
        return None, None

    profile_key = args.osworld_profile_key or env_name
    profile = profiles.get(profile_key)
    if not profile:
        print(f"    WARNING: OSWorld profile key '{profile_key}' not found in {profile_path}")
        return None, None
    print(f"    Loaded OSWorld profile: {profile_key}")
    return _format_osworld_profile(profile), profile


def _category_weight(category: dict) -> float:
    raw = str(category.get("weight", "0")).replace("%", "").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _category_keywords(category: dict) -> set:
    text = " ".join([category.get("name", "")] + category.get("examples", []))
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", text.lower())
    stop = {
        "and", "the", "for", "with", "from", "into", "specific", "simple",
        "task", "tasks", "create", "correct", "requested", "where", "available"
    }
    return {t for t in tokens if t not in stop}


def _primary_task_text(text: str) -> str:
    """Keep classification focused on the user-facing task, not verifier notes."""
    text = re.sub(r"^\s*```(?:markdown)?\s*", "", text.strip(), flags=re.IGNORECASE)
    parts = []

    heading = re.search(r"^#\s+.+$", text, flags=re.MULTILINE)
    if heading:
        parts.append(heading.group(0))

    overview = re.search(
        r"^##\s+Overview\s*(.*?)(?=^##\s+|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if overview:
        parts.append(overview.group(1))

    task_description = re.search(
        r"^##\s+Task Description\s*(.*?)(?=^##\s+|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if task_description:
        body = task_description.group(1)
        goal = re.search(
            r"\*\*Goal:\*\*\s*(.*?)(?=\n\s*\*\*|\n\s*$|\Z)",
            body,
            flags=re.DOTALL | re.IGNORECASE,
        )
        parts.append(goal.group(1) if goal else body[:1000])

    if parts:
        return "\n".join(parts)[:3500]

    lowered = text.lower()
    cut_points = [
        lowered.find(marker)
        for marker in (
            "\n## verification",
            "\n## implementation",
            "\n## setup",
            "\n## evaluator",
            "\n## anti-gaming",
        )
        if lowered.find(marker) != -1
    ]
    if cut_points:
        text = text[: min(cut_points)]
    return text[:2000]


def _rule_based_category(text: str, categories: List[dict]) -> Optional[str]:
    """Prefer high-signal category terms over broad keyword overlap."""
    lowered = _primary_task_text(text).lower()
    available = {category.get("name", "Unnamed category") for category in categories}
    rules = [
        (
            "Downloads, Files, and Print/PDF",
            [
                "download", "downloads", "pdf", "print", "save as pdf",
                "saved file", "downloaded file",
            ],
        ),
        (
            "Bookmarks and Reading Organization",
            ["bookmark", "bookmarks", "bookmark bar", "reading list"],
        ),
        (
            "Accessibility, Translation, and Reader Comfort",
            [
                "a11y", "accessibility", "low vision", "dark reader",
                "dark mode", "reader mode", "reader-friendly", "captions",
                "caption", "translate", "translation", "font size", "zoom level",
                "reading comfort", "focus mode",
            ],
        ),
        (
            "Forms, Autofill, and Web Interaction",
            ["autofill", "form", "forms", "submit", "filter", "sort"],
        ),
        (
            "Extensions, DevTools, and Power User Tasks",
            [
                "devtools", "developer tools", "extension", "extensions",
                "bookmarklet", "snippet", "local storage", "session storage",
                "chrome://flags",
            ],
        ),
        (
            "Navigation, Search, and Active Tab State",
            ["tab", "tabs", "active tab", "pin the", "pinned tab", "navigation"],
        ),
        (
            "History, Cookies, Privacy, and Site Data",
            [
                "browser history", "clear history", "remove history",
                "delete history", "cookie", "cookies", "site data", "privacy",
                "do not track", "tracking", "clear browsing", "cache",
            ],
        ),
        (
            "Chrome Settings and Preferences",
            [
                "startup", "homepage", "home page", "default search",
                "search engine", "pop-up", "popup", "notification permission",
                "settings", "preferences",
            ],
        ),
    ]

    scores = {}
    for name, needles in rules:
        if name in available:
            scores[name] = sum(1 for needle in needles if needle in lowered)
    scored = [(score, name) for name, score in scores.items() if score > 0]
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    return None


def _classify_for_profile(text: str, categories: List[dict]) -> str:
    ruled = _rule_based_category(text, categories)
    if ruled:
        return ruled

    lowered = _primary_task_text(text).lower()
    best_name = "unclassified"
    best_score = 0
    for category in categories:
        score = sum(1 for kw in _category_keywords(category) if kw in lowered)
        if score > best_score:
            best_name = category.get("name", "unclassified")
            best_score = score
    return best_name


def _read_task_text(env_folder: str, task_name: str) -> str:
    task_dir = os.path.join(env_folder, "tasks", task_name)
    parts = []
    for filename in ("task.json", "README.md"):
        path = os.path.join(task_dir, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    parts.append(f.read())
            except OSError:
                pass
    return "\n".join(parts)


def build_osworld_category_schedule(
    profile: Optional[dict],
    env_folder: str,
    max_questions: int,
    target_total: Optional[int],
) -> List[str]:
    """Build a smooth category schedule, compensating for existing task skew."""
    if not profile or not profile.get("categories") or max_questions <= 0:
        return []

    categories = profile["categories"]
    names = [c.get("name", "Unnamed category") for c in categories]
    weights = {c.get("name", "Unnamed category"): _category_weight(c) for c in categories}
    weight_sum = sum(weights.values()) or 1.0

    existing_tasks = get_available_tasks_for_env(env_folder)
    existing_counts = Counter()
    for task_name in existing_tasks:
        text = _read_task_text(env_folder, task_name)
        if text:
            existing_counts[_classify_for_profile(text, categories)] += 1

    final_total = target_total or (len(existing_tasks) + max_questions)
    raw_needed = {}
    for name in names:
        expected_final = final_total * (weights[name] / weight_sum)
        raw_needed[name] = max(0.0, expected_final - existing_counts.get(name, 0))

    raw_sum = sum(raw_needed.values())
    if raw_sum <= 0:
        raw_needed = {name: weights[name] for name in names}
        raw_sum = sum(raw_needed.values()) or 1.0

    desired_float = {name: raw_needed[name] * max_questions / raw_sum for name in names}
    counts = {name: int(desired_float[name]) for name in names}
    remaining_slots = max_questions - sum(counts.values())
    for name, _ in sorted(
        desired_float.items(),
        key=lambda item: item[1] - int(item[1]),
        reverse=True,
    )[:remaining_slots]:
        counts[name] += 1

    print("    OSWorld category quotas for this generation:")
    for name in names:
        print(f"      - {name}: {counts[name]} new tasks (existing classified: {existing_counts.get(name, 0)})")

    schedule = []
    remaining = counts.copy()
    scores = {name: 0 for name in names}
    while len(schedule) < max_questions and sum(remaining.values()) > 0:
        for name in names:
            if remaining[name] > 0:
                scores[name] += counts[name]
        pick = max((name for name in names if remaining[name] > 0), key=lambda n: scores[n])
        schedule.append(pick)
        scores[pick] -= max_questions
        remaining[pick] -= 1
    return schedule


def load_or_save_category_schedule(
    output_dir: str,
    output_prefix: str,
    profile: Optional[dict],
    env_folder: str,
    max_questions: int,
    target_total: Optional[int],
) -> List[str]:
    """Load a stable category schedule or create one for future resumes."""
    if not profile or not profile.get("categories") or max_questions <= 0:
        return []

    path = os.path.join(output_dir, f"{output_prefix}_category_schedule.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            schedule = data.get("schedule", [])
            if isinstance(schedule, list) and len(schedule) >= max_questions:
                print(f"    Loaded stable OSWorld category schedule: {path}")
                return schedule
            print(f"    WARNING: Ignoring invalid category schedule file: {path}")
        except Exception as e:
            print(f"    WARNING: Could not load category schedule '{path}': {e}")

    schedule = build_osworld_category_schedule(profile, env_folder, max_questions, target_total)
    if schedule:
        try:
            counts = Counter(schedule)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "max_questions": max_questions,
                        "target_total": target_total,
                        "schedule": schedule,
                        "counts": dict(counts),
                    },
                    f,
                    indent=2,
                    ensure_ascii=True,
                )
                f.write("\n")
            print(f"    Saved stable OSWorld category schedule: {path}")
        except Exception as e:
            print(f"    WARNING: Could not save category schedule '{path}': {e}")
    return schedule


def main():
    """Main function for enhanced task generation."""
    args = parse_args()

    # Validate paths
    env_folder = os.path.abspath(args.env_folder)
    if not os.path.exists(env_folder):
        print(f"Error: Environment folder not found: {env_folder}")
        sys.exit(1)

    # Setup output directory
    output_dir = args.output_dir or os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 70)
    print("ENHANCED TASK README GENERATION (Step 1)")
    print("=" * 70)
    print(f"Software: {args.software_name}")
    print(f"Environment: {env_folder}")
    print(f"Max questions: {args.max_questions}")
    print(f"Model: {args.model}")
    print("=" * 70)

    # Initialize LLM
    print("\n[1] Initializing LLM...")
    is_gemini = args.model.startswith('gemini')
    try:
        llm = create_llm(
            model=args.model,
            verbose=True,
        )
        model_type = "Gemini" if is_gemini else "Claude"
        print(f"    LLM initialized: {args.model} ({model_type})")
    except Exception as e:
        print(f"Error initializing LLM: {e}")
        sys.exit(1)

    # Initialize progress tracking
    output_prefix = get_output_prefix(args)
    progress = GenerationProgress(output_dir, output_prefix)

    # Resume if enabled
    start_idx = 0
    if args.resume:
        start_idx = progress.load()
        if start_idx > 0:
            print(f"\n[2] Resuming from index {start_idx}...")
        else:
            print("\n[2] Starting fresh (no previous progress found)")
    else:
        print("\n[2] Starting fresh (resume disabled)")

    # Get previously generated task names for deduplication
    previous_tasks = expand_dedup_task_names(progress.get_generated_task_names())

    env_name = os.path.basename(env_folder)

    # Load seed tasks so the LLM knows to avoid regenerating them.
    seed_tasks = get_seed_tasks_for_env(env_folder) or []
    seed_task_names = expand_dedup_task_names([f"{t}@1" for t in seed_tasks])
    if seed_task_names:
        previous_tasks = seed_task_names + previous_tasks
        print(f"    Seed tasks from seed_tasks2.json/seed_tasks.json: {len(seed_task_names)}")
    else:
        print(f"    WARNING: No seed task manifests found under {os.path.join(env_folder, 'tasks')}")

    if args.avoid_existing_tasks:
        existing_task_names = expand_dedup_task_names([f"{t}@1" for t in get_available_tasks_for_env(env_folder)])
        deduped_existing = [t for t in existing_task_names if t not in previous_tasks]
        previous_tasks = deduped_existing + previous_tasks
        print(f"    Existing env tasks added to avoid list: {len(deduped_existing)}")
    print(f"    Previously generated in this run/checkpoint: {len(progress.get_generated_task_names())} tasks")

    # Load extra task names from a previous run's questions pkl (for deduplication + examples)
    prev_readmes = []  # READMEs from previous pkl, used as additional same-env prompt examples
    if args.previous_pkl:
        try:
            with open(args.previous_pkl, 'rb') as f:
                prev_questions = pickle.load(f)
            prev_names = [n for q in prev_questions
                          if (n := extract_task_name_from_response(q))]
            previous_tasks = expand_dedup_task_names(prev_names) + previous_tasks
            # Also keep the full README strings for use as prompt examples
            prev_readmes = [q for q in prev_questions if isinstance(q, str) and len(q) > 100]
            print(f"    Loaded {len(prev_names)} task names from {args.previous_pkl} for deduplication")
            print(f"    Loaded {len(prev_readmes)} READMEs from {args.previous_pkl} for prompt examples")
        except Exception as e:
            print(f"    WARNING: Could not load previous_pkl '{args.previous_pkl}': {e}")

    # Example selection config
    print("\n[3] Example selection config...")
    domain = get_domain_for_software(args.software_name)
    osworld_profile_prompt, osworld_profile_data = load_osworld_profile(args, env_name)
    category_schedule = load_or_save_category_schedule(
        output_dir,
        output_prefix,
        osworld_profile_data,
        env_folder,
        args.max_questions,
        args.osworld_target_total,
    )
    difficulty_info = f", filtered by difficulty: {args.difficulty}" if args.difficulty else ""
    print(f"    Detected domain: {domain or 'general'}")
    prev_readme_seeds = min(5, len(prev_readmes))
    total_examples = args.max_examples + prev_readme_seeds
    print(f"    Examples per task: {args.max_examples} curated + {prev_readme_seeds} from previous pkl = {total_examples} total (randomly selected each iteration{difficulty_info})")

    # Generation loop
    print(f"\n[4] Generating tasks {start_idx} to {args.max_questions - 1}...")
    print("-" * 70)

    for i in tqdm(range(start_idx, args.max_questions), desc="Generating"):
        try:
            # Select fresh random examples for each task (increases diversity)
            examples = select_curated_examples(
                target_env=env_name,
                num_examples=args.max_examples,
                include_same_env=args.include_same_env,
                ensure_verification_diversity=True,
                preferred_domains=[domain] if domain else None,
                difficulty_filter=args.difficulty
            )
            example_readmes = format_examples_for_readme_prompt(examples)

            # Append up to 5 READMEs from previous pkl as additional same-env examples
            if prev_readmes and args.include_same_env > 0:
                sampled = random.sample(prev_readmes, min(5, len(prev_readmes)))
                example_readmes += "\n\n## Additional Same-Environment Examples (from previous run)\n\n"
                example_readmes += "These tasks were generated for the same software in a previous run. "
                example_readmes += "Use them as further style/format reference, but do NOT repeat them.\n\n"
                for j, readme in enumerate(sampled, 1):
                    truncated = readme[:4000] + "\n... [truncated]" if len(readme) > 4000 else readme
                    example_readmes += f"### Previous Example {j}\n\n```markdown\n{truncated.strip()}\n```\n\n---\n\n"

            # Reset conversation for each task
            llm.reset_conversation()

            # Build prompt with updated previous tasks list
            prompt = assemble_task_generation_prompt(
                software_name=args.software_name,
                env_folder=env_folder,
                example_readmes=example_readmes,
                previous_tasks=previous_tasks if previous_tasks else None,
                compact_mode=args.compact_mode,
            )
            if osworld_profile_prompt:
                prompt += "\n\n---\n\n" + osworld_profile_prompt
            target_category = category_schedule[i] if i < len(category_schedule) else None
            if target_category:
                target_info = next(
                    (c for c in osworld_profile_data.get("categories", [])
                     if c.get("name") == target_category),
                    {},
                )
                examples_text = ", ".join(target_info.get("examples", []))
                avoid_text = ", ".join(target_info.get("avoid", []))
                prompt += f"""

---

## REQUIRED CATEGORY FOR THIS SPEC

Target category: **{target_category}**

This category assignment is mandatory for this iteration. Generate a task whose primary user action and primary verification strategy fit this category. Do not drift into generic privacy/settings/bookmark cleanup unless that is the named target category.

Category examples: {examples_text or 'Use the category description from the OSWorld profile.'}

Avoid for this category: {avoid_text or 'Avoid duplicating existing tasks or overused local patterns.'}
"""

            # Add generation instruction
            generation_prompt = prompt + f"""

---

## YOUR TASK

Now generate a NEW, CREATIVE task specification for {args.software_name}.

Remember:
1. Follow the required category assignment above when present
2. Follow the diversity strategy (enumerate activities → random selection → scenario)
3. Match the OSWorld-style distribution profile when provided; preserve local task quality but broaden style/topic coverage
4. Include clear verification strategy
5. Use real data, not synthetic
6. Enable anti-gaming detection

Output the complete task README in markdown format.
"""

            # Generate response
            response = llm.chat(
                generation_prompt,
                temperature=args.temperature,
                max_thinking_tokens=args.max_thinking_tokens,
            )

            # Handle response format differences between Claude and Gemini
            response_text = response['response']
            if isinstance(response_text, list):
                # Claude/Anthropic format: list of content blocks
                response_text = response_text[-1]['text'] if response_text else ""
            elif not isinstance(response_text, str):
                response_text = str(response_text)

            # Extract task name
            print("Extracting task name...")
            task_name = extract_task_name_from_response(response_text)
            print(f"Task name: {task_name}")
            if task_name:
                previous_tasks.extend(expand_dedup_task_names([task_name]))
                tqdm.write(f"  Generated: {task_name}")
            else:
                tqdm.write(f"  Generated task (could not extract name)")

            # Save progress
            print("Saving progress...")
            progress.add_result(
                question=response_text,
                response=response['response_obj'],
                messages=llm.get_conversation()
            )

        except KeyboardInterrupt:
            print("\n\nInterrupted! Saving progress...")
            progress.save()
            print(f"Progress saved at index {i}")
            sys.exit(0)

        except Exception as e:
            tqdm.write(f"  Error at index {i}: {e}")
            # Continue to next task
            continue

    # Final save
    print("\n[5] Saving final results...")
    progress.save()

    print("\n" + "=" * 70)
    print("GENERATION COMPLETE")
    print("=" * 70)
    print(f"Total tasks generated: {len(progress.questions)}")
    print(f"Output files:")
    print(f"  - {output_prefix}_questions.pkl")
    print(f"  - {output_prefix}_responses.pkl")
    print(f"  - {output_prefix}_messages.pkl")
    print("\nNext step: Run main_files_any_app_enhanced.py to generate implementation files")


if __name__ == "__main__":
    main()
