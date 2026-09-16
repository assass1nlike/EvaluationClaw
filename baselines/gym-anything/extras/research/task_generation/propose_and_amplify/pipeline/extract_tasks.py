#!/usr/bin/env python3
"""
Extract generated tasks from pickle files to task folders.

Usage:
    python -m enhanced.extract_tasks \
        --questions_file "enhanced_files_*_questions.pkl" \
        --output_dir "benchmarks/cua_world/environments/slicer3d_env/tasks"

    # Or auto-detect files:
    python -m enhanced.extract_tasks \
        --software_name "Slicer3D" \
        --output_dir "benchmarks/cua_world/environments/slicer3d_env/tasks"
"""

import os
import re
import json
import argparse
import pickle
from glob import glob
from typing import Dict, List, Optional, Tuple


def extract_task_name_from_response(response: str) -> Optional[str]:
    """Extract task name from response text."""
    # Try to find task name in markdown title format
    match = re.search(r'`([a-zA-Z0-9_]+)@\d+`', response[:500])
    if match:
        return match.group(1)

    # Try to extract from task.json code block (handles both ```task.json and ```json)
    if '```task.json' in response:
        try:
            start = response.find('```task.json')
            end = response.find('```', start + 12)
            if end > start:
                json_str = response[start + 12:end].strip()
                task_data = json.loads(json_str)
                task_id = task_data.get('id', '')
                if '@' in task_id:
                    return task_id.split('@')[0]
        except (json.JSONDecodeError, KeyError):
            pass

    # Try to extract from generic ```json block that contains task id
    # This handles Gemini's tendency to use ```json instead of ```task.json
    json_block_pattern = r'```json\s*\n(\{.*?"id"\s*:\s*"[^"]+@\d+".*?\})\s*```'
    match = re.search(json_block_pattern, response, re.DOTALL)
    if match:
        try:
            json_str = match.group(1)
            task_data = json.loads(json_str)
            task_id = task_data.get('id', '')
            if '@' in task_id:
                return task_id.split('@')[0]
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: search for any "id": "taskname@version" pattern in the response
    id_pattern = r'"id"\s*:\s*"([a-zA-Z0-9_]+)@\d+"'
    match = re.search(id_pattern, response)
    if match:
        return match.group(1)

    return None


def extract_files_from_response(response: str) -> Dict[str, str]:
    """Extract all files from a response.

    Looks for patterns like:
    ```filename.ext
    content
    ```

    Also handles Gemini's tendency to use generic language markers:
    - ```json for task.json
    - ```bash for shell scripts
    - ```python for verifier.py
    """
    files = {}

    # Pattern to match code blocks with filenames
    # Matches: ```task.json, ```setup_task.sh, ```verifier.py, etc.
    pattern = r'```([a-zA-Z0-9_]+\.[a-zA-Z]+)\n(.*?)```'

    matches = re.findall(pattern, response, re.DOTALL)
    for filename, content in matches:
        # Clean up content
        content = content.strip()
        files[filename] = content

    # Handle Gemini's generic code block markers
    # If we don't have task.json, try to find it in ```json blocks
    if 'task.json' not in files:
        # Pattern 1: ```json\n{...} - JSON directly after marker
        json_pattern = r'```json\s*\n(\{.*?"id"\s*:\s*"[^"]+@\d+".*?\})\s*```'
        match = re.search(json_pattern, response, re.DOTALL)
        if match:
            files['task.json'] = match.group(1).strip()

    # Pattern 2: Gemini sometimes uses ```json\ntask.json\n{...} format
    if 'task.json' not in files:
        json_label_pattern = r'```json\s*\ntask\.json\s*\n(\{.*?\})\s*```'
        match = re.search(json_label_pattern, response, re.DOTALL)
        if match:
            files['task.json'] = match.group(1).strip()

    # Pattern 3: Gemini sometimes uses ```json\n"task.json"\n{...} format (with quotes)
    if 'task.json' not in files:
        json_quoted_label_pattern = r'```json\s*\n"task\.json"\s*\n(\{.*?\})\s*```'
        match = re.search(json_quoted_label_pattern, response, re.DOTALL)
        if match:
            files['task.json'] = match.group(1).strip()

    # Handle generic ```bash blocks - try to identify by content
    bash_pattern = r'```bash\s*\n(.*?)```'
    bash_matches = re.findall(bash_pattern, response, re.DOTALL)
    for i, content in enumerate(bash_matches):
        content = content.strip()

        # Strip leading filename labels that Gemini sometimes adds
        # Patterns: "setup_task.sh"\n, setup_task.sh\n, "export_result.sh"\n, etc.
        content = re.sub(r'^["\']?(?:setup_task\.sh|export_result\.sh)["\']?\s*\n', '', content)

        # Identify by content
        if 'setup_task.sh' not in files and ('Setting up' in content or 'setup' in content.lower()[:100] or 'task_start_time' in content):
            files['setup_task.sh'] = content
        elif 'export_result.sh' not in files and ('Export' in content or 'task_result.json' in content or 'task_end' in content.lower()):
            files['export_result.sh'] = content

    # Handle generic ```python blocks for verifier
    if 'verifier.py' not in files:
        python_pattern = r'```python\s*\n(.*?def verify_.*?)\s*```'
        match = re.search(python_pattern, response, re.DOTALL)
        if match:
            content = match.group(1).strip()
            # Strip leading filename labels
            content = re.sub(r'^["\']?verifier\.py["\']?\s*\n', '', content)
            files['verifier.py'] = content

    return files


def save_task_files(
    task_name: str,
    files: Dict[str, str],
    output_dir: str,
    overwrite: bool = False
) -> Tuple[bool, str]:
    """Save task files to disk.

    Returns:
        (success, message)
    """
    task_dir = os.path.join(output_dir, task_name)

    # Check if already exists
    if os.path.exists(task_dir) and not overwrite:
        return False, f"Task {task_name} already exists (use --overwrite to replace)"

    # Create directory
    os.makedirs(task_dir, exist_ok=True)

    # Save files
    saved_files = []
    for filename, content in files.items():
        filepath = os.path.join(task_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        # Make shell scripts executable
        if filename.endswith('.sh'):
            os.chmod(filepath, 0o755)

        saved_files.append(filename)

    return True, f"Saved {len(saved_files)} files: {', '.join(saved_files)}"


def validate_task_files(files: Dict[str, str]) -> List[str]:
    """Validate that required files are present and valid.

    Returns list of warnings/errors.
    """
    warnings = []

    required_files = ['task.json', 'verifier.py']
    optional_files = ['setup_task.sh', 'export_result.sh', 'README.md']

    for req in required_files:
        if req not in files:
            warnings.append(f"Missing required file: {req}")

    # Validate task.json
    if 'task.json' in files:
        try:
            task_data = json.loads(files['task.json'])
            if 'id' not in task_data:
                warnings.append("task.json missing 'id' field")
            if 'description' not in task_data:
                warnings.append("task.json missing 'description' field")
        except json.JSONDecodeError as e:
            warnings.append(f"task.json is invalid JSON: {e}")

    # Check verifier.py has the function
    if 'verifier.py' in files:
        content = files['verifier.py']
        if 'def verify_' not in content:
            warnings.append("verifier.py missing verify_* function")
        if 'copy_from_env' not in content:
            warnings.append("verifier.py may be missing copy_from_env pattern")

    return warnings


def load_pickle(filepath: str):
    """Load pickle file."""
    with open(filepath, 'rb') as f:
        return pickle.load(f)


def find_questions_file(directory: str, software_name: str) -> Optional[str]:
    """Find the questions pickle file for a software."""
    software_clean = software_name.replace(' ', '_')
    patterns = [
        f"enhanced_files_*_{software_clean}_questions.pkl",
        f"*_files_*_{software_clean}_questions.pkl",
    ]

    for pattern in patterns:
        matches = glob(os.path.join(directory, pattern))
        if matches:
            # Return newest file
            matches.sort(key=os.path.getmtime, reverse=True)
            return matches[0]

    return None


def main():
    parser = argparse.ArgumentParser(description='Extract generated tasks to folders')

    parser.add_argument('--questions_file', type=str, default=None,
                        help='Path to questions pickle file (from Step 2)')
    parser.add_argument('--software_name', type=str, default=None,
                        help='Software name to auto-detect pickle file')
    parser.add_argument('--output_dir', type=str, required=True,
                        help='Output directory for tasks (e.g., benchmarks/cua_world/environments/env_name/tasks)')
    parser.add_argument('--overwrite', action='store_true',
                        help='Overwrite existing tasks')
    parser.add_argument('--validate', action='store_true', default=True,
                        help='Validate generated files')
    parser.add_argument('--dry_run', action='store_true',
                        help='Show what would be done without saving')
    parser.add_argument('--max_tasks', type=int, default=None,
                        help='Maximum number of tasks to extract')

    args = parser.parse_args()

    # Find questions file
    if args.questions_file:
        questions_file = args.questions_file
    elif args.software_name:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        questions_file = find_questions_file(script_dir, args.software_name)
        if not questions_file:
            print(f"Error: Could not find questions file for {args.software_name}")
            return 1
        print(f"Found questions file: {os.path.basename(questions_file)}")
    else:
        print("Error: Must specify --questions_file or --software_name")
        return 1

    # Load questions
    print(f"\nLoading {questions_file}...")
    questions = load_pickle(questions_file)
    print(f"Loaded {len(questions)} generated responses")

    # Create output directory
    output_dir = os.path.abspath(args.output_dir)
    if not args.dry_run:
        os.makedirs(output_dir, exist_ok=True)

    print(f"Output directory: {output_dir}")
    print()

    # Process each response
    stats = {'extracted': 0, 'skipped': 0, 'errors': 0, 'warnings': 0}

    for i, response in enumerate(questions):
        if args.max_tasks and stats['extracted'] >= args.max_tasks:
            break

        # Extract task name
        task_name = extract_task_name_from_response(response)
        if not task_name:
            print(f"  [{i}] Could not extract task name - SKIPPED")
            stats['skipped'] += 1
            continue

        # Extract files
        files = extract_files_from_response(response)
        if not files:
            print(f"  [{i}] {task_name}: No files found - SKIPPED")
            stats['skipped'] += 1
            continue

        # Validate
        warnings = []
        if args.validate:
            warnings = validate_task_files(files)
            if warnings:
                stats['warnings'] += len(warnings)

        # Save or dry-run
        if args.dry_run:
            status = "WOULD SAVE"
            file_list = ', '.join(files.keys())
            print(f"  [{i}] {task_name}: {status} ({file_list})")
            if warnings:
                for w in warnings:
                    print(f"       WARNING: {w}")
        else:
            success, message = save_task_files(
                task_name, files, output_dir, args.overwrite
            )
            if success:
                stats['extracted'] += 1
                print(f"  [{i}] {task_name}: {message}")
                if warnings:
                    for w in warnings:
                        print(f"       WARNING: {w}")
            else:
                stats['skipped'] += 1
                print(f"  [{i}] {task_name}: {message}")

    # Summary
    print()
    print("=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"  Extracted: {stats['extracted']}")
    print(f"  Skipped:   {stats['skipped']}")
    print(f"  Warnings:  {stats['warnings']}")

    if not args.dry_run and stats['extracted'] > 0:
        print(f"\nTasks saved to: {output_dir}")
        print("\nNext steps:")
        print("  1. Review the generated files")
        print("  2. Test tasks with: python test_env.py --task <task_name>")

    return 0


if __name__ == "__main__":
    exit(main())
