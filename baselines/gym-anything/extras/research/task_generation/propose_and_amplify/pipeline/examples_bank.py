"""
Curated Example Bank for Enhanced Task Generation

This module provides a structured collection of high-quality task examples
categorized by verification pattern, complexity, and domain.
"""

import os
import json
import random
from glob import glob
from typing import List, Dict, Tuple, Optional

# Base path for environments (the canonical location of envs in the
# gym-anything repo). Override with GYM_ANYTHING_ENV_BASE if you keep envs
# somewhere else.
def _resolve_env_base() -> str:
    override = os.environ.get("GYM_ANYTHING_ENV_BASE")
    if override:
        return os.path.abspath(override)
    here = os.path.dirname(os.path.abspath(__file__))
    # extras/research/task_generation/propose_and_amplify/pipeline/ → repo root
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", "..", ".."))
    return os.path.join(repo_root, "benchmarks", "cua_world", "environments")


EXAMPLES_BASE = _resolve_env_base()


# =============================================================================
# CURATED EXAMPLE BANK
# =============================================================================

# Examples categorized by verification pattern type
VERIFICATION_PATTERN_EXAMPLES = {
    # Database verification - query DB tables for created/modified records
    "database_query": [
        ("opensis_env", "add_student"),
        ("opensis_env", "add_grade"),
        ("opensis_env", "create_course"),
        ("opensis_env", "record_attendance"),
        ("openemr_env", "add_patient"),
        ("moodle_env", "create_course"),
        ("magento_env", "add_product"),
    ],

    # File-based verification - check output files for content/existence
    "file_based": [
        ("slicer3d_env", "brats_tumor_segmentation"),
        ("blender3d_env", "render_basic_scene"),
        ("gimp_env", "export_jpg"),
        ("libreoffice_writer_env", "create_document"),
        ("davinci_resolve_env", "export_video"),
    ],

    # VLM hybrid - combine programmatic checks with visual verification
    "vlm_hybrid": [
        ("astroimagej_env", "detect_exoplanet_transit"),
        ("astroimagej_env", "measure_star_photometry"),
        ("google_earth_env", "navigate_to_location"),
        ("google_earth_env", "create_placemark"),
        ("slicer3d_env", "load_sample_data"),
        ("weasis_env", "measure_distance"),
    ],

    # API/state-based - query application internal state
    "api_state": [
        ("vscode_env", "git_commit"),
        ("vscode_env", "install_extension"),
        ("chrome_env_all", "bookmark_organize"),
        ("intellij_idea_env", "create_project"),
        ("dbeaver_env", "create_connection"),
    ],

    # VLM-only verification - for UI tasks without programmatic access
    "vlm_only": [
        ("google_earth_env", "search_coordinates"),
        ("opensis_env", "search_student"),
        ("chrome_env_all", "appearance_dark_mode"),
    ],
}

# Examples categorized by task complexity
COMPLEXITY_EXAMPLES = {
    # Simple single-action tasks
    "simple_single_action": [
        ("android_calculator_env", "basic_addition"),
        ("blender3d_env", "add_sphere_to_scene"),
        ("chrome_env_all", "appearance_dark_mode"),
        ("slicer3d_env", "load_sample_data"),
    ],

    # Multi-step workflow tasks
    "multi_step_workflow": [
        ("astroimagej_env", "detect_exoplanet_transit"),
        ("slicer3d_env", "brats_tumor_segmentation"),
        ("opensis_env", "add_student"),
        ("vscode_env", "git_commit"),
        ("blender3d_env", "render_basic_scene"),
    ],

    # Tasks requiring error recovery
    "error_recovery": [
        ("davinci_resolve_env", "import_and_edit"),
        ("intellij_idea_env", "debug_project"),
    ],

    # Configuration tasks
    "configuration": [
        ("chrome_env_all", "autofill_address_config"),
        ("vscode_env", "configure_settings"),
        ("thunderbird_env", "setup_account"),
    ],
}

# Examples categorized by domain
DOMAIN_EXAMPLES = {
    "medical_imaging": [
        ("slicer3d_env", "brats_tumor_segmentation"),
        ("slicer3d_env", "load_sample_data"),
        ("weasis_env", "measure_distance"),
        ("weasis_env", "load_dicom"),
    ],

    "astronomy": [
        ("astroimagej_env", "detect_exoplanet_transit"),
        ("astroimagej_env", "measure_star_photometry"),
    ],

    "geospatial": [
        ("google_earth_env", "navigate_to_location"),
        ("google_earth_env", "create_placemark"),
        ("google_earth_env", "measure_distance"),
        ("qgis_env", "load_shapefile"),
    ],

    "document_editing": [
        ("libreoffice_writer_env", "create_document"),
        ("libreoffice_calc_env", "create_formula"),
        ("libreoffice_impress_env", "create_presentation"),
        ("onlyoffice_env", "format_document"),
    ],

    "software_development": [
        ("vscode_env", "git_commit"),
        ("vscode_env", "install_extension"),
        ("intellij_idea_env", "create_project"),
        ("dbeaver_env", "create_connection"),
    ],

    "web_administration": [
        ("opensis_env", "add_student"),
        ("openemr_env", "add_patient"),
        ("moodle_env", "create_course"),
        ("magento_env", "add_product"),
        ("woo_commerce_env", "add_product"),
        ("odoo_env", "create_invoice"),
        ("splunk_env", "create_dashboard"),
    ],

    "media_production": [
        ("blender3d_env", "render_basic_scene"),
        ("davinci_resolve_env", "export_video"),
        ("opentoonz_env", "create_animation"),
        ("vlc_media_player_env", "convert_format"),
    ],

    "browser_productivity": [
        ("chrome_env_all", "bookmark_organize"),
        ("chrome_env_all", "print_to_pdf"),
        ("chrome_env_all", "devtools_snippet_create"),
    ],

    "communication": [
        ("thunderbird_env", "compose_email"),
        ("thunderbird_env", "setup_account"),
    ],
}

# High-quality examples that demonstrate best practices
HIGH_QUALITY_EXAMPLES = [
    # VLM trajectory verification (5/5 quality)
    ("astroimagej_env", "detect_exoplanet_transit"),

    # File-based + VLM hybrid (5/5 quality)
    ("slicer3d_env", "brats_tumor_segmentation"),
    ("blender3d_env", "render_basic_scene"),

    # Database + VLM fallback (4/5 quality)
    ("opensis_env", "add_student"),
    ("opensis_env", "add_grade"),

    # VLM with landmarks (3/5 quality but good for visual tasks)
    ("google_earth_env", "navigate_to_location"),
    ("google_earth_env", "create_placemark"),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_env_folder(env_name: str) -> str:
    """Get the full path to an environment folder."""
    return os.path.join(EXAMPLES_BASE, env_name)


def get_task_folder(env_name: str, task_name: str) -> str:
    """Get the full path to a task folder."""
    return os.path.join(EXAMPLES_BASE, env_name, 'tasks', task_name)


def task_exists(env_name: str, task_name: str) -> bool:
    """Check if a task exists."""
    task_folder = get_task_folder(env_name, task_name)
    return os.path.exists(os.path.join(task_folder, 'task.json'))


def get_available_tasks_for_env(env_folder: str) -> List[str]:
    """
    Get list of available tasks for an environment by reading from disk.

    WARNING: For example selection, use get_oldest_tasks_for_env() instead!
    This returns all tasks without filtering.

    This function is useful for:
    - Validation and debugging
    - Listing tasks for user display
    - Post-generation analysis
    """
    tasks_dir = os.path.join(env_folder, 'tasks')
    if not os.path.exists(tasks_dir):
        return []

    tasks = []
    for item in os.listdir(tasks_dir):
        task_path = os.path.join(tasks_dir, item)
        if os.path.isdir(task_path) and os.path.exists(os.path.join(task_path, 'task.json')):
            tasks.append(item)
    return tasks


def get_seed_tasks_for_env(env_folder: str) -> Optional[List[str]]:
    """
    Load seed tasks from seed_tasks2.json and seed_tasks.json if they exist.

    seed_tasks2.json is the OSWorld-style second seed bank. It is deliberately
    preferred ahead of seed_tasks.json so new expansion runs see these examples
    first while still retaining the original manually snapshotted seeds.

    Returns:
        List of seed task names, or None if no seed manifest exists.
    """
    seed_files = [
        os.path.join(env_folder, 'tasks', 'seed_tasks2.json'),
        os.path.join(env_folder, 'tasks', 'seed_tasks.json'),
    ]
    tasks = []
    for seed_file in seed_files:
        if not os.path.exists(seed_file):
            continue
        try:
            with open(seed_file, 'r') as f:
                loaded = json.load(f)
            for task_name in loaded:
                if task_name not in tasks:
                    tasks.append(task_name)
        except (json.JSONDecodeError, IOError):
            pass
    if tasks:
        return tasks
    return None


def get_oldest_tasks_for_env(env_folder: str, max_tasks: int = 5, difficulty_filter: Optional[List[str]] = None) -> List[str]:
    """
    Get seed tasks for an environment.

    Prefers seed_tasks.json (snapshotted once via snapshot_seed_tasks.py).
    Falls back to oldest-by-mtime if seed_tasks.json doesn't exist yet.

    Args:
        env_folder: Path to the environment folder
        max_tasks: Maximum number of tasks to return (default: 5)
        difficulty_filter: Optional list of difficulty levels to filter by (e.g., ["easy", "very easy"])

    Returns:
        List of task names
    """
    # Prefer explicit seed_tasks.json
    seeds = get_seed_tasks_for_env(env_folder)
    if seeds is not None:
        tasks = seeds[:max_tasks]
        # Apply difficulty filter if specified
        if difficulty_filter:
            normalized_filter = [d.lower().strip() for d in difficulty_filter]
            filtered = []
            for task_name in tasks:
                task_json_path = os.path.join(env_folder, 'tasks', task_name, 'task.json')
                try:
                    with open(task_json_path, 'r') as f:
                        task_data = json.load(f)
                    if task_data.get('difficulty', '').lower().strip() in normalized_filter:
                        filtered.append(task_name)
                except (json.JSONDecodeError, IOError):
                    continue
            return filtered
        return tasks

    # Fallback: sort by modification time (oldest first)
    tasks_dir = os.path.join(env_folder, 'tasks')
    if not os.path.exists(tasks_dir):
        return []

    # Normalize difficulty filter to lowercase
    normalized_filter = None
    if difficulty_filter:
        normalized_filter = [d.lower().strip() for d in difficulty_filter]

    tasks_with_time = []
    for item in os.listdir(tasks_dir):
        task_path = os.path.join(tasks_dir, item)
        task_json_path = os.path.join(task_path, 'task.json')
        if os.path.isdir(task_path) and os.path.exists(task_json_path):
            # Filter by difficulty if specified
            if normalized_filter:
                try:
                    with open(task_json_path, 'r') as f:
                        task_data = json.load(f)
                    task_difficulty = task_data.get('difficulty', '').lower().strip()
                    if task_difficulty not in normalized_filter:
                        continue  # Skip this task
                except (json.JSONDecodeError, IOError):
                    continue  # Skip if can't read task.json

            # Use task.json modification time as creation proxy
            mtime = os.path.getmtime(task_json_path)
            tasks_with_time.append((item, mtime))

    # Sort by time (oldest first)
    tasks_with_time.sort(key=lambda x: x[1])

    # Return only task names, limited to max_tasks
    return [task for task, _ in tasks_with_time[:max_tasks]]


def get_task_files(env_name: str, task_name: str) -> Dict[str, str]:
    """Get all files for a task as a dict of filename -> content."""
    task_folder = get_task_folder(env_name, task_name)
    if not os.path.exists(task_folder):
        return {}

    files = {}
    for pattern in ['*.json', '*.md', '*.sh', '*.py']:
        for filepath in glob(os.path.join(task_folder, pattern)):
            filename = os.path.basename(filepath)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    files[filename] = f.read()
            except Exception:
                pass
    return files


def get_task_readme(env_name: str, task_name: str) -> Optional[str]:
    """Get the README.md content for a task."""
    readme_path = os.path.join(get_task_folder(env_name, task_name), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return None


def get_verifier_content(env_name: str, task_name: str) -> Optional[str]:
    """Get the verifier.py content for a task."""
    verifier_path = os.path.join(get_task_folder(env_name, task_name), 'verifier.py')
    if os.path.exists(verifier_path):
        with open(verifier_path, 'r', encoding='utf-8') as f:
            return f.read()
    return None


# =============================================================================
# SMART EXAMPLE SELECTION
# =============================================================================

def select_curated_examples(
    target_env: str,
    num_examples: int = 5,
    include_same_env: int = 2,
    ensure_verification_diversity: bool = True,
    preferred_domains: Optional[List[str]] = None,
    difficulty_filter: Optional[str] = None
) -> List[Tuple[str, str]]:
    """
    Select diverse, high-quality examples for task generation.

    Example selection strategy:
    - Same-env examples: Uses oldest tasks from disk (first 5 by creation time)
      These are safe because oldest tasks are typically manually vetted.
    - Other-env examples: Uses hardcoded curated lists only.
      This prevents newly generated tasks from other envs being used.

    Args:
        target_env: The target environment name (e.g., 'chrome_env_all')
        num_examples: Total number of examples to select
        include_same_env: Number of examples to include from the same environment
        ensure_verification_diversity: If True, ensures examples cover different verification types
        preferred_domains: List of domain names to prioritize
        difficulty_filter: Optional comma-separated string of difficulty levels (e.g., "easy,very easy")

    Returns:
        List of (env_name, task_name) tuples
    """
    selected = []
    used_verification_types = set()

    # Parse difficulty filter (comma-separated string to list)
    parsed_difficulty = None
    if difficulty_filter:
        parsed_difficulty = [d.strip() for d in difficulty_filter.split(',')]

    # Step 1: ALWAYS include examples from the same environment
    # Use oldest tasks (by creation time) - these are typically manually vetted
    # This is safe because newly generated tasks will be newest, not oldest
    env_folder = get_env_folder(target_env)
    oldest_tasks = get_oldest_tasks_for_env(env_folder, max_tasks=5, difficulty_filter=parsed_difficulty)

    if oldest_tasks:
        # Select up to include_same_env from the oldest tasks
        same_env_selected = oldest_tasks[:include_same_env]
        for task in same_env_selected:
            selected.append((target_env, task))

    # Step 2: Include examples from different verification patterns (CURATED LISTS ONLY)
    # For other-env examples, we only use hardcoded curated lists to avoid bad patterns
    if ensure_verification_diversity:
        verification_types = ["database_query", "file_based", "vlm_hybrid", "api_state"]
        random.shuffle(verification_types)

        for vtype in verification_types:
            if len(selected) >= num_examples:
                break
            if vtype in used_verification_types:
                continue

            candidates = VERIFICATION_PATTERN_EXAMPLES.get(vtype, [])
            # Filter out same env and already selected
            candidates = [
                (env, task) for env, task in candidates
                if env != target_env and (env, task) not in selected and task_exists(env, task)
            ]

            if candidates:
                example = random.choice(candidates)
                selected.append(example)
                used_verification_types.add(vtype)

    # Step 3: Fill remaining slots from preferred domains or high-quality examples
    while len(selected) < num_examples:
        if preferred_domains:
            # Try preferred domains first
            for domain in preferred_domains:
                if len(selected) >= num_examples:
                    break
                candidates = DOMAIN_EXAMPLES.get(domain, [])
                candidates = [
                    (env, task) for env, task in candidates
                    if env != target_env and (env, task) not in selected and task_exists(env, task)
                ]
                if candidates:
                    selected.append(random.choice(candidates))

        # Fall back to high-quality examples
        remaining_high_quality = [
            (env, task) for env, task in HIGH_QUALITY_EXAMPLES
            if env != target_env and (env, task) not in selected and task_exists(env, task)
        ]

        if remaining_high_quality:
            selected.append(random.choice(remaining_high_quality))
        else:
            # Absolute fallback - any available task
            all_examples = []
            for vtype_examples in VERIFICATION_PATTERN_EXAMPLES.values():
                all_examples.extend(vtype_examples)

            remaining = [
                (env, task) for env, task in all_examples
                if env != target_env and (env, task) not in selected and task_exists(env, task)
            ]

            if remaining:
                selected.append(random.choice(remaining))
            else:
                break  # No more examples available

    return selected[:num_examples]


def select_examples_by_verification_type(
    verification_type: str,
    num_examples: int = 3,
    exclude_envs: Optional[List[str]] = None
) -> List[Tuple[str, str]]:
    """
    Select examples of a specific verification type.

    Args:
        verification_type: One of 'database_query', 'file_based', 'vlm_hybrid', 'api_state', 'vlm_only'
        num_examples: Number of examples to select
        exclude_envs: List of environment names to exclude

    Returns:
        List of (env_name, task_name) tuples
    """
    exclude_envs = exclude_envs or []

    candidates = VERIFICATION_PATTERN_EXAMPLES.get(verification_type, [])
    candidates = [
        (env, task) for env, task in candidates
        if env not in exclude_envs and task_exists(env, task)
    ]

    if len(candidates) <= num_examples:
        return candidates

    return random.sample(candidates, num_examples)


def select_examples_by_domain(
    domain: str,
    num_examples: int = 3,
    exclude_envs: Optional[List[str]] = None
) -> List[Tuple[str, str]]:
    """
    Select examples from a specific domain.

    Args:
        domain: Domain name from DOMAIN_EXAMPLES
        num_examples: Number of examples to select
        exclude_envs: List of environment names to exclude

    Returns:
        List of (env_name, task_name) tuples
    """
    exclude_envs = exclude_envs or []

    candidates = DOMAIN_EXAMPLES.get(domain, [])
    candidates = [
        (env, task) for env, task in candidates
        if env not in exclude_envs and task_exists(env, task)
    ]

    if len(candidates) <= num_examples:
        return candidates

    return random.sample(candidates, num_examples)


def get_domain_for_software(software_name: str) -> Optional[str]:
    """
    Infer the domain based on software name.

    Args:
        software_name: Name of the software (e.g., 'Chrome Browser', '3D Slicer')

    Returns:
        Domain name or None if not found
    """
    software_lower = software_name.lower()

    domain_keywords = {
        "medical_imaging": ["slicer", "weasis", "medical", "dicom", "radiology"],
        "astronomy": ["astro", "imagej", "telescope", "photometry"],
        "geospatial": ["earth", "qgis", "gis", "maps", "geo"],
        "document_editing": ["libreoffice", "word", "writer", "calc", "excel", "impress", "office"],
        "software_development": ["vscode", "intellij", "ide", "code", "developer", "programming"],
        "web_administration": ["opensis", "openemr", "moodle", "magento", "woo", "odoo", "splunk", "admin"],
        "media_production": ["blender", "davinci", "resolve", "opentoonz", "vlc", "video", "render"],
        "browser_productivity": ["chrome", "browser", "firefox", "web"],
        "communication": ["thunderbird", "email", "mail"],
    }

    for domain, keywords in domain_keywords.items():
        if any(kw in software_lower for kw in keywords):
            return domain

    return None


# =============================================================================
# CONTENT FORMATTING
# =============================================================================

def format_task_for_prompt(
    env_name: str,
    task_name: str,
    include_files: List[str] = None,
    max_file_length: int = 5000
) -> str:
    """
    Format a task's files for inclusion in a prompt.

    Args:
        env_name: Environment name
        task_name: Task name
        include_files: List of file names to include (default: all)
        max_file_length: Maximum length per file content

    Returns:
        Formatted string with all task files
    """
    include_files = include_files or ['task.json', 'README.md', 'setup_task.sh', 'export_result.sh', 'verifier.py']

    task_folder = get_task_folder(env_name, task_name)
    if not os.path.exists(task_folder):
        return f"# Task {task_name} (from {env_name}) - NOT FOUND\n"

    content = f"## Task: {task_name} (from {env_name})\n\n"

    files = get_task_files(env_name, task_name)

    for filename in include_files:
        if filename in files:
            file_content = files[filename]
            if len(file_content) > max_file_length:
                file_content = file_content[:max_file_length] + "\n... [truncated]"
            content += f"```{filename}\n{file_content.strip()}\n```\n\n"

    return content


def format_examples_for_readme_prompt(examples: List[Tuple[str, str]]) -> str:
    """
    Format examples for the task README generation prompt (Step 1).
    Only includes README.md files to teach task specification format.
    """
    content = "## Example Task Specifications\n\n"
    content += "Here are example task specifications to guide your task creation:\n\n"

    for i, (env_name, task_name) in enumerate(examples, 1):
        readme = get_task_readme(env_name, task_name)
        if readme:
            content += f"### Example {i}: {task_name} (from {env_name})\n\n"
            # Truncate very long READMEs
            if len(readme) > 4000:
                readme = readme[:4000] + "\n... [truncated]"
            content += f"```markdown\n{readme.strip()}\n```\n\n"
            content += "---\n\n"

    return content


def format_examples_for_files_prompt(examples: List[Tuple[str, str]]) -> str:
    """
    Format examples for the implementation files generation prompt (Step 2).
    Includes all files: task.json, setup_task.sh, export_result.sh, verifier.py
    """
    content = "## Example Task Implementations\n\n"
    content += "Here are complete task implementations to guide your file generation:\n\n"

    for i, (env_name, task_name) in enumerate(examples, 1):
        content += f"### Example {i}: {task_name} (from {env_name})\n\n"
        content += format_task_for_prompt(env_name, task_name)
        content += "---\n\n"

    return content


# =============================================================================
# VERIFICATION PATTERN DETECTION
# =============================================================================

def detect_verification_pattern(verifier_content: str) -> str:
    """
    Detect the verification pattern used in a verifier.py file.

    Returns one of: 'database_query', 'file_based', 'vlm_hybrid', 'api_state', 'vlm_only', 'unknown'
    """
    if not verifier_content:
        return "unknown"

    content_lower = verifier_content.lower()

    # Check for database queries
    has_db = any(kw in content_lower for kw in ['mysql', 'sqlite', 'postgresql', 'exec_in_env', 'database', 'query'])

    # Check for file operations
    has_file = any(kw in content_lower for kw in ['copy_from_env', 'tempfile', 'os.path', 'file_size', 'read()', 'json.load'])

    # Check for VLM
    has_vlm = any(kw in content_lower for kw in ['query_vlm', 'vlm', 'get_final_screenshot', 'sample_trajectory'])

    # Check for API state
    has_api = any(kw in content_lower for kw in ['mrmlscene', 'slicer.', 'api', 'state', 'getnode'])

    # Determine pattern
    if has_vlm:
        if has_file or has_db or has_api:
            return "vlm_hybrid"
        else:
            return "vlm_only"
    elif has_db:
        return "database_query"
    elif has_file:
        return "file_based"
    elif has_api:
        return "api_state"
    else:
        return "unknown"


# =============================================================================
# INITIALIZATION
# =============================================================================

def validate_example_bank():
    """Validate that example bank entries actually exist."""
    missing = []
    for category_name, examples_dict in [
        ("VERIFICATION_PATTERN_EXAMPLES", VERIFICATION_PATTERN_EXAMPLES),
        ("DOMAIN_EXAMPLES", DOMAIN_EXAMPLES),
        ("COMPLEXITY_EXAMPLES", COMPLEXITY_EXAMPLES),
    ]:
        for subcategory, examples in examples_dict.items():
            for env_name, task_name in examples:
                if not task_exists(env_name, task_name):
                    missing.append((category_name, subcategory, env_name, task_name))

    if missing:
        print(f"Warning: {len(missing)} example tasks not found:")
        for cat, subcat, env, task in missing[:10]:
            print(f"  - {cat}/{subcat}: {env}/{task}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")

    return missing


if __name__ == "__main__":
    # Validate bank on import
    print("Validating example bank...")
    missing = validate_example_bank()
    print(f"Validation complete. {len(missing)} missing tasks.")

    # Test selection
    print("\nTesting example selection for 'chrome_env_all'...")
    examples = select_curated_examples('chrome_env_all', num_examples=5)
    for env, task in examples:
        print(f"  - {env}/{task}")
