#!/usr/bin/env python3
"""
Enhanced Task Implementation File Generation (Step 2)

This script generates implementation files (task.json, setup_task.sh,
export_result.sh, verifier.py) with enhanced guidance including VLM
verification patterns, copy_from_env usage, and multi-criteria scoring.

Supports parallel execution for faster generation.

Usage:
    python main_files_any_app_enhanced.py \
        --software_name "Chrome Browser" \
        --env_folder "benchmarks/cua_world/environments/chrome_env_all" \
        --messages_file "enhanced_claude-sonnet-4-20250514_Chrome_Browser_messages.pkl" \
        --num_workers 4
"""

import os
import sys
import argparse
import pickle
import time
import random
from typing import List, Optional, Dict, Any, Tuple
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path for imports
# (path manipulation removed: package uses relative imports)

from .examples_bank import (
    select_curated_examples,
    select_examples_by_verification_type,
    format_examples_for_files_prompt,
    get_domain_for_software,
    get_task_files,
)
from .prompt_components import (
    assemble_file_generation_prompt,
    TASK_FILES_OUTPUT_FORMAT,
)
from .verification_templates import (
    get_compact_vlm_summary,
    get_compact_errors_summary,
    get_compact_scoring_summary,
    TWO_PART_VERIFICATION,
)
from .utils_enhanced import (
    EnhancedAnthropicLLM,
    GeminiLLM,
    create_llm,
    GenerationProgress,
    extract_task_name_from_response,
    parse_task_files,
    validate_task_files,
    load_pickle,
    save_pickle,
    get_project_root,
)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Enhanced Task File Generation')

    # Required arguments
    parser.add_argument('--software_name', type=str, required=True,
                        help='Name of the target software')
    parser.add_argument('--env_folder', type=str, required=True,
                        help='Path to environment folder')

    # Input files
    parser.add_argument('--messages_file', type=str, default=None,
                        help='Path to messages pickle from Step 1')
    parser.add_argument('--questions_file', type=str, default=None,
                        help='Path to questions pickle from Step 1')

    # Optional arguments
    parser.add_argument('--max_questions', type=int, default=None,
                        help='Maximum tasks to process (default: all)')
    parser.add_argument('--max_examples', type=int, default=5,
                        help='Number of examples to show in prompt')
    parser.add_argument('--model', type=str, default='claude-sonnet-4-20250514',
                        help='Model to use')
    parser.add_argument('--step1_model', type=str, default=None,
                        help='Step 1 model name (used in output prefix for hybrid runs)')
    parser.add_argument('--resume', type=bool, default=True,
                        help='Resume from last checkpoint')
    parser.add_argument('--output_dir', type=str, default=None,
                        help='Output directory')
    parser.add_argument('--temperature', type=float, default=1.0,
                        help='Sampling temperature')
    parser.add_argument('--max_thinking_tokens', type=int, default=16384,
                        help='Max thinking tokens')
    parser.add_argument('--compact_mode', type=bool, default=True,
                        help='Use compact prompt mode to save tokens')
    parser.add_argument('--validate', type=bool, default=True,
                        help='Validate generated files')
    parser.add_argument('--num_workers', type=int, default=4,
                        help='Number of parallel workers (default: 4)')
    parser.add_argument('--max_retries', type=int, default=5,
                        help='Max retries on rate limit errors (default: 5)')
    parser.add_argument('--retry_base_delay', type=float, default=10.0,
                        help='Base delay in seconds for exponential backoff (default: 10)')
    parser.add_argument('--retry_max_delay', type=float, default=300.0,
                        help='Max delay in seconds for exponential backoff (default: 300)')
    parser.add_argument('--include_same_env', type=int, default=None,
                        help='Number of same-env seed task examples to include (default: same as --max_examples). '
                             'Set to 0 to disable same-env examples (for ablation).')

    return parser.parse_args()


def get_output_prefix(args) -> str:
    """Generate output file prefix."""
    step2_model = args.model.replace('/', '-')
    software_name = args.software_name.replace(' ', '_')
    if args.step1_model:
        step1_model = args.step1_model.replace('/', '-')
        return f"enhanced_files_{step1_model}+{step2_model}_{software_name}"
    return f"enhanced_files_{step2_model}_{software_name}"


def auto_detect_input_files(args, output_dir: str):
    """Auto-detect input files from Step 1 if not specified."""
    if args.messages_file and args.questions_file:
        return

    software_name = args.software_name.replace(' ', '_')
    step2_model_slug = args.model.replace('/', '-')
    step1_model_slug = args.step1_model.replace('/', '-') if args.step1_model else None

    # Collect all candidate step-1 files (exclude step-2 "enhanced_files_" outputs)
    messages_candidates = []
    questions_candidates = []
    for filename in sorted(os.listdir(output_dir)):  # sorted for determinism
        if software_name not in filename:
            continue
        if filename.startswith('enhanced_files_'):
            continue  # skip step-2 outputs
        if 'messages.pkl' in filename:
            messages_candidates.append(filename)
        elif 'questions.pkl' in filename:
            questions_candidates.append(filename)

    def pick_best(candidates, label):
        if not candidates:
            return None
        # 1. Prefer explicit step1_model match
        if step1_model_slug:
            matches = [f for f in candidates if step1_model_slug in f]
            if len(matches) == 1:
                print(f"  Auto-detected {label} (step1_model match): {matches[0]}")
                return os.path.join(output_dir, matches[0])
        # 2. Prefer same model as step 2
        matches = [f for f in candidates if step2_model_slug in f]
        if len(matches) == 1:
            print(f"  Auto-detected {label} (same-model match): {matches[0]}")
            return os.path.join(output_dir, matches[0])
        # 3. Exactly one candidate total — use it
        if len(candidates) == 1:
            print(f"  Auto-detected {label}: {candidates[0]}")
            return os.path.join(output_dir, candidates[0])
        # 4. Ambiguous — abort with a clear error
        raise ValueError(
            f"Multiple Step 1 {label} files found for '{software_name}', cannot auto-detect:\n"
            + "\n".join(f"  {f}" for f in candidates)
            + "\nPlease pass --messages_file / --questions_file explicitly."
        )

    if not args.messages_file:
        args.messages_file = pick_best(messages_candidates, 'messages file')
    if not args.questions_file:
        args.questions_file = pick_best(questions_candidates, 'questions file')


def is_rate_limit_error(error: Exception) -> bool:
    """Check if an exception is a rate limit error (429)."""
    error_str = str(error).lower()
    return (
        '429' in error_str or
        'rate_limit' in error_str or
        'rate limit' in error_str or
        'request_limit_exceeded' in error_str or
        'too many requests' in error_str
    )


def process_single_task(
    task_idx: int,
    conversation: List[Dict],
    file_gen_prompt_base: str,
    model: str,
    temperature: float,
    max_thinking_tokens: int,
    validate: bool,
    max_retries: int = 5,
    retry_base_delay: float = 10.0,
    retry_max_delay: float = 300.0,
) -> Dict[str, Any]:
    """
    Process a single task - designed to be called in parallel.

    Each call creates its own LLM instance to avoid shared state issues.
    Includes exponential backoff retry for rate limit errors.

    Returns a dict with:
        - idx: task index
        - success: bool
        - response_text: generated text
        - response_obj: raw response object
        - messages: conversation history
        - files: parsed files dict
        - validation: validation results (if enabled)
        - error: error message (if failed)
        - retries: number of retries needed
    """
    result = {
        'idx': task_idx,
        'success': False,
        'response_text': None,
        'response_obj': None,
        'messages': None,
        'files': None,
        'validation': None,
        'error': None,
        'retries': 0,
    }

    try:
        # Create a fresh LLM instance for this worker
        llm = create_llm(
            model=model,
            verbose=False  # Reduce noise in parallel execution
        )

        # Set conversation to continue from Step 1
        llm.set_conversation(conversation)

        # Build prompt for file generation
        file_gen_prompt = file_gen_prompt_base + f"""

---

## YOUR TASK

Now generate the implementation files for the task you designed above.

Create these files:
1. task.json - with proper hooks and metadata
2. setup_task.sh - with initial state recording and timestamp
3. export_result.sh - with JSON export and timestamp checking
4. verifier.py - with multi-criteria scoring using copy_from_env

CRITICAL REMINDERS:
- Use copy_from_env, NOT exec_in_env
- Use trajectory frames for VLM, NOT just final screenshot
- Include timestamp checks for anti-gaming
- Return {{"passed": bool, "score": int, "feedback": str}}

Output each file in a code block with the filename.
"""

        # Generate response with retry logic for rate limits
        response = None
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                response = llm.chat(
                    file_gen_prompt,
                    temperature=temperature,
                    max_thinking_tokens=max_thinking_tokens,
                )
                break  # Success, exit retry loop

            except Exception as e:
                last_error = e
                if is_rate_limit_error(e) and attempt < max_retries:
                    # Calculate delay with exponential backoff + jitter
                    delay = min(
                        retry_base_delay * (2 ** attempt) + random.uniform(0, 5),
                        retry_max_delay
                    )
                    result['retries'] = attempt + 1
                    tqdm.write(f"  Task {task_idx}: Rate limited, retry {attempt + 1}/{max_retries} after {delay:.1f}s")
                    time.sleep(delay)
                else:
                    # Not a rate limit error or max retries exceeded
                    raise

        if response is None:
            raise last_error or Exception("No response received")

        # Handle response format differences between Claude and Gemini
        response_text = response['response']
        if isinstance(response_text, list):
            # Claude/Anthropic format: list of content blocks
            response_text = response_text[-1]['text'] if response_text else ""
        elif not isinstance(response_text, str):
            response_text = str(response_text)

        result['response_text'] = response_text
        result['response_obj'] = response['response_obj']
        result['messages'] = llm.get_conversation()

        # Parse generated files
        files = parse_task_files(response_text)
        result['files'] = files

        # Validate if enabled
        if validate and files:
            validation = validate_task_files(files)
            result['validation'] = validation

        result['success'] = True

    except Exception as e:
        result['error'] = str(e)

    return result


def main():
    """Main function for enhanced file generation."""
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
    print("ENHANCED TASK FILE GENERATION (Step 2)")
    print("=" * 70)
    print(f"Software: {args.software_name}")
    print(f"Environment: {env_folder}")
    print(f"Model: {args.model}")
    print(f"Parallel workers: {args.num_workers}")
    print("=" * 70)

    # Auto-detect input files
    print("\n[1] Locating input files...")
    auto_detect_input_files(args, output_dir)

    if not args.messages_file:
        print("Error: Could not find messages file from Step 1")
        print("Please specify --messages_file")
        sys.exit(1)

    # Load input data
    print("\n[2] Loading Step 1 results...")
    messages_data = load_pickle(args.messages_file)
    if not messages_data:
        print(f"Error: Could not load {args.messages_file}")
        sys.exit(1)
    print(f"    Loaded {len(messages_data)} conversation histories")

    questions_data = None
    if args.questions_file:
        questions_data = load_pickle(args.questions_file)
        print(f"    Loaded {len(questions_data)} task READMEs")

    # Determine how many tasks to process
    num_tasks = len(messages_data)
    if args.max_questions:
        num_tasks = min(num_tasks, args.max_questions)
    print(f"    Will process {num_tasks} tasks")

    # Initialize LLM
    print("\n[3] Initializing LLM...")
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
    # breakpoint()
    progress = GenerationProgress(output_dir, output_prefix)

    # Resume if enabled
    start_idx = 0
    if args.resume:
        start_idx = progress.load()
        if start_idx > 0:
            print(f"\n[4] Resuming from index {start_idx}...")
        else:
            print("\n[4] Starting fresh")
    else:
        print("\n[4] Starting fresh (resume disabled)")

    # Select curated implementation examples
    print("\n[5] Selecting curated implementation examples...")
    env_name = os.path.basename(env_folder)
    domain = get_domain_for_software(args.software_name)

    # Bucket 1: up to max_examples from OTHER envs (diverse verification patterns)
    other_env_raw = []
    for vtype in ['file_based', 'database_query', 'vlm_hybrid']:
        vtype_examples = select_examples_by_verification_type(
            vtype,
            num_examples=2,
            exclude_envs=[env_name]
        )
        other_env_raw.extend(vtype_examples)
    seen = set()
    other_env_examples = []
    for e, t in other_env_raw:
        if (e, t) not in seen:
            seen.add((e, t))
            other_env_examples.append((e, t))
    other_env_examples = other_env_examples[:args.max_examples]

    # Bucket 2: up to max_examples from SAME env (seed tasks)
    include_same = args.include_same_env if args.include_same_env is not None else args.max_examples
    same_env_raw = select_curated_examples(
        target_env=env_name,
        num_examples=args.max_examples,
        include_same_env=include_same,
        ensure_verification_diversity=False
    )
    same_env_examples = [(e, t) for e, t in same_env_raw if e == env_name][:args.max_examples]

    examples = other_env_examples + same_env_examples

    print(f"    Selected {len(other_env_examples)} other-env + {len(same_env_examples)} same-env examples:")
    for env, task in examples:
        print(f"      - {env}/{task}")

    # Format examples for prompt
    example_implementations = format_examples_for_files_prompt(examples)

    # Build file generation prompt template
    file_gen_prompt_base = assemble_file_generation_prompt(
        example_implementations=example_implementations,
        compact_mode=args.compact_mode
    )

    # Generation loop
    print(f"\n[6] Generating files for tasks {start_idx} to {num_tasks - 1}...")
    print(f"    Using {args.num_workers} worker(s)")
    print("-" * 70)

    validation_results = {'passed': 0, 'failed': 0, 'warnings': [], 'total_retries': 0}
    task_indices = list(range(start_idx, num_tasks))

    if args.num_workers <= 1:
        # Sequential execution (original behavior)
        for i in tqdm(task_indices, desc="Generating"):
            try:
                # Get conversation history from Step 1
                conversation = messages_data[i]

                # Set LLM conversation to continue from Step 1
                llm.set_conversation(conversation)

                # Build prompt for file generation
                file_gen_prompt = file_gen_prompt_base + f"""

---

## YOUR TASK

Now generate the implementation files for the task you designed above.

Create these files:
1. task.json - with proper hooks and metadata
2. setup_task.sh - with initial state recording and timestamp
3. export_result.sh - with JSON export and timestamp checking
4. verifier.py - with multi-criteria scoring using copy_from_env

CRITICAL REMINDERS:
- Use copy_from_env, NOT exec_in_env
- Use trajectory frames for VLM, NOT just final screenshot
- Include timestamp checks for anti-gaming
- Return {{"passed": bool, "score": int, "feedback": str}}

Output each file in a code block with the filename.
"""

                # Generate response
                response = llm.chat(
                    file_gen_prompt,
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

                # Parse generated files
                files = parse_task_files(response_text)

                # Validate if enabled
                if args.validate and files:
                    validation = validate_task_files(files)
                    all_valid = all(v[0] for v in validation.values())

                    if all_valid:
                        validation_results['passed'] += 1
                        tqdm.write(f"  Task {i}: VALID ({len(files)} files)")
                    else:
                        validation_results['failed'] += 1
                        errors = [f"{f}: {v[1]}" for f, v in validation.items() if not v[0]]
                        validation_results['warnings'].append((i, errors))
                        tqdm.write(f"  Task {i}: INVALID - {errors[0] if errors else 'unknown'}")
                else:
                    tqdm.write(f"  Task {i}: Generated {len(files)} files")

                # Save progress
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
                continue
    else:
        # Parallel execution
        print(f"    Launching parallel generation with {args.num_workers} workers...")

        # Collect results to add in order
        results_by_idx: Dict[int, Dict[str, Any]] = {}
        completed_count = 0
        lock = threading.Lock()

        def submit_task(idx: int):
            """Submit a single task for processing."""
            return process_single_task(
                task_idx=idx,
                conversation=messages_data[idx],
                file_gen_prompt_base=file_gen_prompt_base,
                model=args.model,
                temperature=args.temperature,
                max_thinking_tokens=args.max_thinking_tokens,
                validate=args.validate,
                max_retries=args.max_retries,
                retry_base_delay=args.retry_base_delay,
                retry_max_delay=args.retry_max_delay,
            )

        try:
            with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
                # Submit all tasks
                future_to_idx = {
                    executor.submit(submit_task, idx): idx
                    for idx in task_indices
                }

                # Process results as they complete
                with tqdm(total=len(task_indices), desc="Generating") as pbar:
                    for future in as_completed(future_to_idx):
                        idx = future_to_idx[future]
                        try:
                            result = future.result()
                            results_by_idx[idx] = result

                            # Update validation stats and display
                            if result['success']:
                                files = result['files']
                                validation = result['validation']
                                retries = result.get('retries', 0)
                                validation_results['total_retries'] += retries
                                retry_info = f" (retried {retries}x)" if retries > 0 else ""

                                if args.validate and files and validation:
                                    all_valid = all(v[0] for v in validation.values())

                                    if all_valid:
                                        validation_results['passed'] += 1
                                        tqdm.write(f"  Task {idx}: VALID ({len(files)} files){retry_info}")
                                    else:
                                        validation_results['failed'] += 1
                                        errors = [f"{f}: {v[1]}" for f, v in validation.items() if not v[0]]
                                        validation_results['warnings'].append((idx, errors))
                                        tqdm.write(f"  Task {idx}: INVALID - {errors[0] if errors else 'unknown'}{retry_info}")
                                else:
                                    tqdm.write(f"  Task {idx}: Generated {len(files) if files else 0} files{retry_info}")
                            else:
                                tqdm.write(f"  Task {idx}: ERROR - {result['error']}")

                        except Exception as e:
                            tqdm.write(f"  Task {idx}: EXCEPTION - {e}")
                            results_by_idx[idx] = {
                                'idx': idx,
                                'success': False,
                                'error': str(e),
                            }

                        pbar.update(1)

        except KeyboardInterrupt:
            print("\n\nInterrupted! Saving completed results...")
            # Fall through to save what we have

        # Add results to progress in order
        print("\n    Saving results in order...")
        for idx in sorted(results_by_idx.keys()):
            result = results_by_idx[idx]
            if result['success']:
                progress.add_result(
                    question=result['response_text'],
                    response=result['response_obj'],
                    messages=result['messages']
                )

    # Final save
    print("\n[7] Saving final results...")
    progress.save()

    # Print summary
    print("\n" + "=" * 70)
    print("GENERATION COMPLETE")
    print("=" * 70)
    print(f"Total tasks processed: {len(progress.questions)}")
    if args.num_workers > 1:
        print(f"Execution mode: Parallel ({args.num_workers} workers)")
        if validation_results['total_retries'] > 0:
            print(f"Total rate limit retries: {validation_results['total_retries']}")
    else:
        print(f"Execution mode: Sequential")

    if args.validate:
        print(f"\nValidation Results:")
        print(f"  Passed: {validation_results['passed']}")
        print(f"  Failed: {validation_results['failed']}")

        if validation_results['warnings']:
            print(f"\nFirst 5 validation warnings:")
            for idx, errors in validation_results['warnings'][:5]:
                print(f"  Task {idx}: {errors[0]}")

    print(f"\nOutput files:")
    print(f"  - {output_prefix}_questions.pkl (generated files)")
    print(f"  - {output_prefix}_responses.pkl")
    print(f"  - {output_prefix}_messages.pkl")

    print("\nNext step: Extract files and test tasks")


if __name__ == "__main__":
    main()
