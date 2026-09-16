"""Stage implementations for propose-and-amplify task generation.

Each module corresponds to one pipeline stage:
- ``main_any_app_enhanced``  — proposer (Opus seeds) and amplifier (Gemini)
- ``merge``                  — concatenate proposer + amplifier pickles
- ``main_files_any_app_enhanced`` — fill in setup_task.sh / verifier.py / etc.
- ``extract_tasks``          — write final task folders under tasks/

Use ``method.py`` (one level up) as the entry point; this package's modules
are intended to be invoked through the staged driver, not directly.
"""

from .examples_bank import (
    select_curated_examples,
    select_examples_by_verification_type,
    select_examples_by_domain,
    format_examples_for_readme_prompt,
    format_examples_for_files_prompt,
    get_domain_for_software,
    get_seed_tasks_for_env,
    get_available_tasks_for_env,
)
from .prompt_components import (
    assemble_task_generation_prompt,
    assemble_file_generation_prompt,
)
from .utils_enhanced import (
    EnhancedAnthropicLLM,
    GeminiLLM,
    GenerationProgress,
    create_llm,
    extract_task_name_from_response,
    parse_task_files,
    validate_task_files,
    save_task_files,
    load_pickle,
    save_pickle,
    get_project_root,
    get_examples_dir,
    get_env_notes_dir,
)

__all__ = [
    "EnhancedAnthropicLLM",
    "GeminiLLM",
    "GenerationProgress",
    "assemble_file_generation_prompt",
    "assemble_task_generation_prompt",
    "create_llm",
    "extract_task_name_from_response",
    "format_examples_for_files_prompt",
    "format_examples_for_readme_prompt",
    "get_available_tasks_for_env",
    "get_domain_for_software",
    "get_env_notes_dir",
    "get_examples_dir",
    "get_project_root",
    "get_seed_tasks_for_env",
    "load_pickle",
    "parse_task_files",
    "save_pickle",
    "save_task_files",
    "select_curated_examples",
    "select_examples_by_domain",
    "select_examples_by_verification_type",
    "validate_task_files",
]
