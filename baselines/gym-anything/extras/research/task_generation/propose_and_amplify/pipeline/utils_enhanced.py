"""
Enhanced Utilities for Task Generation

This module provides utility functions for the enhanced task generation system,
including LLM wrappers, document loading, and file management.
"""

import os
import re
import json
import pickle
import time
import uuid
from glob import glob
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path
import random


# =============================================================================
# USAGE LOGGING
# =============================================================================

USAGE_DUMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model_usage_dumps')


def log_usage(response_obj: Any, model: str):
    """
    Log usage from a response object to model_usage_dumps/.

    Args:
        response_obj: The raw response object from the API
        model: Model name/ID
    """
    try:
        usage = getattr(response_obj, 'usage', None)
        if usage is None:
            return

        os.makedirs(USAGE_DUMP_DIR, exist_ok=True)
        filename = f"{uuid.uuid4()}_{model.replace('/', '-')}.pkl"
        filepath = os.path.join(USAGE_DUMP_DIR, filename)

        with open(filepath, 'wb') as f:
            pickle.dump(usage, f)
    except Exception as e:
        print(f"Error logging usage: {e}")
        pass


# =============================================================================
# PATH CONFIGURATION
# =============================================================================

# This module sits at:
#   extras/research/task_generation/propose_and_amplify/pipeline/utils_enhanced.py
# Repo root is 5 levels up.
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = MODULE_DIR
METHOD_DIR = os.path.dirname(PIPELINE_DIR)
PROJECT_ROOT = os.path.abspath(os.path.join(METHOD_DIR, "..", "..", "..", ".."))


def get_project_root() -> str:
    """Get the gym-anything project root directory."""
    return os.environ.get("GYM_ANYTHING_PROJECT_ROOT") or PROJECT_ROOT


def get_examples_dir() -> str:
    """Get the directory holding env folders (defaults to benchmarks/cua_world/environments)."""
    override = os.environ.get("GYM_ANYTHING_ENV_BASE")
    if override:
        return os.path.abspath(override)
    return os.path.join(get_project_root(), "benchmarks", "cua_world", "environments")


def get_env_notes_dir() -> str:
    """Get the env_creation_notes directory (the creation_audit prompts)."""
    override = os.environ.get("GYM_ANYTHING_ENV_NOTES")
    if override:
        return os.path.abspath(override)
    return os.path.join(
        get_project_root(),
        "extras",
        "research",
        "software_as_env",
        "creation_audit",
        "memory",
        "env_creation_notes",
    )


# Backwards-compatible aliases for code that imports these names directly.
EXAMPLES_DIR = get_examples_dir()
ENV_NOTES_DIR = get_env_notes_dir()


# =============================================================================
# DOCUMENT LOADING AND SUMMARIZATION
# =============================================================================

def load_markdown_file(filepath: str) -> Optional[str]:
    """Load a markdown file's content."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Warning: Could not load {filepath}: {e}")
    return None


def load_env_creation_notes() -> Dict[str, str]:
    """
    Load all env_creation_notes markdown files.

    Returns:
        Dict mapping filename to content
    """
    notes = {}

    # Load top-level notes
    for filepath in glob(os.path.join(ENV_NOTES_DIR, '*.md')):
        filename = os.path.basename(filepath)
        content = load_markdown_file(filepath)
        if content:
            notes[filename] = content

    # Load verifier notes
    verifier_dir = os.path.join(ENV_NOTES_DIR, 'verifiers')
    for filepath in glob(os.path.join(verifier_dir, '*.md')):
        filename = f"verifiers/{os.path.basename(filepath)}"
        content = load_markdown_file(filepath)
        if content:
            notes[filename] = content

    return notes


def extract_section(content: str, section_title: str) -> Optional[str]:
    """
    Extract a section from markdown content by heading.

    Args:
        content: Full markdown content
        section_title: Title to search for (without # prefix)

    Returns:
        Section content or None if not found
    """
    # Build regex to match section
    # Matches "## Section Title" or "### Section Title" etc
    pattern = rf'^(#+)\s*{re.escape(section_title)}\s*$'

    lines = content.split('\n')
    start_idx = None
    start_level = None

    for i, line in enumerate(lines):
        match = re.match(pattern, line, re.IGNORECASE)
        if match:
            start_idx = i
            start_level = len(match.group(1))
            break

    if start_idx is None:
        return None

    # Find end of section (next heading at same or higher level)
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        heading_match = re.match(r'^(#+)\s+', lines[i])
        if heading_match:
            level = len(heading_match.group(1))
            if level <= start_level:
                end_idx = i
                break

    return '\n'.join(lines[start_idx:end_idx])


def summarize_document(content: str, max_length: int = 5000) -> str:
    """
    Summarize a document by extracting key sections.

    Args:
        content: Full document content
        max_length: Maximum output length

    Returns:
        Summarized content
    """
    if len(content) <= max_length:
        return content

    # Extract key sections (headings)
    lines = content.split('\n')
    key_lines = []
    current_section = []

    for line in lines:
        if line.startswith('#'):
            # Heading - always include
            if current_section and len('\n'.join(key_lines + current_section)) < max_length:
                key_lines.extend(current_section)
            current_section = [line]
        else:
            current_section.append(line)

        # Check length
        total = '\n'.join(key_lines + current_section)
        if len(total) > max_length:
            break

    return '\n'.join(key_lines)


def load_verification_guidance() -> Dict[str, str]:
    """
    Load key verification guidance documents.

    Returns:
        Dict with 'vlm_patterns', 'verification_patterns', 'common_errors'
    """
    guidance = {}

    # Load VLM patterns
    vlm_path = os.path.join(ENV_NOTES_DIR, 'vlm_checklist_patterns.md')
    guidance['vlm_patterns'] = load_markdown_file(vlm_path) or ""

    # Load verification patterns
    verif_path = os.path.join(ENV_NOTES_DIR, '09_verification_patterns.md')
    guidance['verification_patterns'] = load_markdown_file(verif_path) or ""

    # Extract common errors section
    if guidance['verification_patterns']:
        errors = extract_section(guidance['verification_patterns'], 'Common Errors')
        guidance['common_errors'] = errors or ""
    else:
        guidance['common_errors'] = ""

    return guidance


# =============================================================================
# TASK EXTRACTION AND PARSING
# =============================================================================

def extract_task_name_from_response(response: str) -> Optional[str]:
    """
    Extract task name from LLM response.

    Looks for pattern: `task_name@version`

    Args:
        response: LLM response text

    Returns:
        Task name string or None
    """
    # Look for backtick-enclosed task names
    pattern = r'`([a-zA-Z0-9_]+@\d+)`'
    matches = re.findall(pattern, response[:500])

    if matches:
        return matches[0]

    # Fallback: look for pattern without backticks
    pattern2 = r'([a-zA-Z0-9_]+@\d+)'
    matches2 = re.findall(pattern2, response[:500])

    if matches2:
        return matches2[0]

    return None


def extract_task_title(response: str) -> Optional[str]:
    """
    Extract task title from response (the # heading line).

    Args:
        response: LLM response text

    Returns:
        Title string or None
    """
    # Look for markdown heading with task name
    lines = response.split('\n')
    for line in lines[:10]:
        if line.startswith('# ') and '`' in line:
            return line.strip('# ').strip()

    return None


def extract_code_blocks(response: str) -> Dict[str, str]:
    """
    Extract code blocks from response, keyed by filename.

    Looks for patterns like:
    ```filename.ext
    content
    ```

    Args:
        response: LLM response text

    Returns:
        Dict mapping filename to content
    """
    blocks = {}

    # Pattern: ```filename\ncontent\n```
    pattern = r'```([a-zA-Z0-9_\-\.]+)\n(.*?)```'
    matches = re.findall(pattern, response, re.DOTALL)

    for filename, content in matches:
        # Clean up filename
        filename = filename.strip()
        if filename:
            blocks[filename] = content.strip()

    return blocks


def parse_task_files(response: str) -> Dict[str, str]:
    """
    Parse task implementation files from LLM response.

    Expected files: task.json, setup_task.sh, export_result.sh, verifier.py, README.md

    Args:
        response: LLM response text

    Returns:
        Dict mapping filename to content
    """
    blocks = extract_code_blocks(response)

    # Normalize common variations
    normalized = {}
    for filename, content in blocks.items():
        # Handle variations like "task.json" vs "task_json"
        if 'task' in filename.lower() and 'json' in filename.lower():
            normalized['task.json'] = content
        elif 'setup' in filename.lower() and 'sh' in filename.lower():
            normalized['setup_task.sh'] = content
        elif 'export' in filename.lower() and 'sh' in filename.lower():
            normalized['export_result.sh'] = content
        elif 'verifier' in filename.lower() and 'py' in filename.lower():
            normalized['verifier.py'] = content
        elif 'readme' in filename.lower():
            normalized['README.md'] = content
        else:
            normalized[filename] = content

    return normalized


# =============================================================================
# FILE MANAGEMENT
# =============================================================================

def save_task_files(
    task_folder: str,
    files: Dict[str, str],
    overwrite: bool = False
) -> List[str]:
    """
    Save task files to disk.

    Args:
        task_folder: Path to task folder
        files: Dict mapping filename to content
        overwrite: Whether to overwrite existing files

    Returns:
        List of saved file paths
    """
    os.makedirs(task_folder, exist_ok=True)
    saved = []

    for filename, content in files.items():
        filepath = os.path.join(task_folder, filename)

        if os.path.exists(filepath) and not overwrite:
            print(f"Skipping existing file: {filepath}")
            continue

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            saved.append(filepath)

            # Make shell scripts executable
            if filename.endswith('.sh'):
                os.chmod(filepath, 0o755)

        except Exception as e:
            print(f"Error saving {filepath}: {e}")

    return saved


def load_pickle(filepath: str) -> Any:
    """Load a pickle file."""
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            return pickle.load(f)
    return None


def save_pickle(data: Any, filepath: str):
    """Save data to a pickle file."""
    with open(filepath, 'wb') as f:
        pickle.dump(data, f)


# =============================================================================
# LLM WRAPPER (Enhanced)
# =============================================================================

# Try to import litellm for Gemini support
try:
    import litellm
    HAS_LITELLM = True
except ImportError:
    HAS_LITELLM = False


class GeminiLLM:
    """
    Gemini LLM wrapper using litellm with thinking/reasoning support.

    Designed for gemini-3-flash-preview with high reasoning effort.
    """

    def __init__(
        self,
        model: str = "gemini-3-flash-preview",
        messages: Optional[List] = None,
        verbose: bool = True
    ):
        if not HAS_LITELLM:
            raise ImportError("litellm package not installed. Install with: pip install litellm")

        self.model = model
        self.messages = messages or []
        self.verbose = verbose

        # Ensure GEMINI_API_KEY is set
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            # Try loading from .env files
            self._load_env_file()
            api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")

    def _load_env_file(self):
        """Try to load .env file from question_generation directory."""
        env_path = os.path.join(QUESTION_GEN_DIR, '.env')
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            os.environ[key] = value
            except Exception as e:
                if self.verbose:
                    print(f"Warning: Could not load .env file: {e}")

    def chat(
        self,
        user_input: str,
        model: Optional[str] = None,
        max_tokens: int = 40000,
        temperature: float = 1.0,
        max_thinking_tokens: int = 16384,
        n: int = 1,
        cache_last: bool = True,
        retry_count: int = 3,
        retry_delay: float = 2.0,
        reasoning_effort: str = 'high',
        timeout: int = 600,
    ) -> Dict[str, Any]:
        """
        Send a message and get response from Gemini.

        Args:
            user_input: User message
            model: Model to use (default: self.model)
            max_tokens: Max response tokens
            temperature: Sampling temperature
            max_thinking_tokens: Not used for Gemini, but kept for API compatibility
            n: Number of responses (not used for Gemini)
            cache_last: Not used for Gemini, but kept for API compatibility
            retry_count: Number of retries on failure
            retry_delay: Delay between retries
            reasoning_effort: Gemini reasoning effort ('low', 'medium', 'high')
            timeout: Request timeout in seconds

        Returns:
            Dict with 'response', 'think_text', 'response_obj'
        """
        model = model or self.model
        reasoning_effort = os.environ.get("GEMINI_REASONING_EFFORT", reasoning_effort)

        # Build message in OpenAI-compatible format for litellm
        user_message = {
            'role': 'user',
            'content': user_input
        }

        # Convert conversation history to litellm format
        messages = []
        for msg in self.messages:
            if isinstance(msg, dict):
                if 'content' in msg:
                    content = msg['content']
                    # Handle Anthropic-style content (list of content blocks)
                    if isinstance(content, list):
                        text_content = ''
                        for block in content:
                            if isinstance(block, dict) and 'text' in block:
                                text_content += block['text']
                            elif isinstance(block, dict) and hasattr(block, 'text'):
                                text_content += block.text
                        content = text_content
                    messages.append({
                        'role': msg['role'],
                        'content': content if isinstance(content, str) else str(content)
                    })

        messages.append(user_message)

        # Try with retries
        last_error = None
        for attempt in range(retry_count):
            try:
                response = self._call_gemini(
                    messages, model, max_tokens, temperature,
                    reasoning_effort, timeout
                )

                # Update conversation history
                self.messages = messages
                self.messages.append({
                    'role': 'assistant',
                    'content': response['response']
                })

                # Log usage
                log_usage(response['response_obj'], model)

                return response

            except Exception as e:
                last_error = e
                if self.verbose:
                    print(f"Attempt {attempt + 1}/{retry_count} failed: {e}")
                if attempt < retry_count - 1:
                    time.sleep(retry_delay * (attempt + 1))

        raise last_error

    def _call_gemini(
        self,
        messages: List,
        model: str,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str,
        timeout: int
    ) -> Dict[str, Any]:
        """Call Gemini API via litellm."""
        completion_kwargs = {
            "model": 'gemini/' + model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning_effort,
            "timeout": timeout,
        }
        if os.environ.get("GEMINI_ENABLE_TOOLS") == "1":
            completion_kwargs["tools"] = [
                {"google_search": {}},
                {"code_execution": {}},
            ]

        response = litellm.completion(**completion_kwargs)

        # Extract response text
        response_text = response.choices[0].message.content
        think_text = ""

        # Gemini with reasoning includes thinking in the response
        # The thinking tokens are used internally, not exposed directly
        # but we can try to detect structured thinking patterns
        if hasattr(response.choices[0].message, 'reasoning'):
            think_text = response.choices[0].message.reasoning or ""

        return {
            'response': response_text,
            'think_text': think_text,
            'response_obj': response
        }

    def reset_conversation(self):
        """Reset conversation history."""
        self.messages = []

    def set_conversation(self, messages: List):
        """Set conversation history."""
        self.messages = messages

    def get_conversation(self) -> List:
        """Get conversation history."""
        return self.messages

    def save(self, filepath: str):
        """Save LLM state to pickle."""
        save_pickle(self, filepath)

    @classmethod
    def load(cls, filepath: str) -> 'GeminiLLM':
        """Load LLM state from pickle."""
        return load_pickle(filepath)


class EnhancedAnthropicLLM:
    """
    Enhanced LLM wrapper with better error handling and logging.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        messages: Optional[List] = None,
        verbose: bool = True
    ):
        self.model = model
        self.messages = messages or []
        self.verbose = verbose

        # Initialize client
        try:
            from anthropic import Anthropic
            self.client = Anthropic()
        except ImportError:
            raise ImportError("anthropic package not installed")

    def chat(
        self,
        user_input: str,
        model: Optional[str] = None,
        max_tokens: int = 40000,
        temperature: float = 1.0,
        max_thinking_tokens: int = 16384,
        n: int = 1,
        cache_last: bool = True,
        retry_count: int = 10,
        retry_delay: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Send a message and get response.

        Args:
            user_input: User message
            model: Model to use (default: self.model)
            max_tokens: Max response tokens
            temperature: Sampling temperature
            max_thinking_tokens: Max thinking tokens
            n: Number of responses (for Anthropic, always 1)
            cache_last: Whether to cache the last message
            retry_count: Number of retries on failure
            retry_delay: Delay between retries

        Returns:
            Dict with 'response', 'think_text', 'response_obj'
        """
        model = model or self.model

        # Build message
        user_message = {
            'role': 'user',
            'content': [{'type': 'text', 'text': user_input}]
        }
        if cache_last:
            user_message['content'][0]['cache_control'] = {'type': 'ephemeral'}

        messages = self.messages + [user_message]

        # Try with retries
        last_error = None
        for attempt in range(retry_count):
            try:
                response = self._call_anthropic(messages, model, max_tokens, temperature, max_thinking_tokens)

                # Update conversation history
                self.messages = messages
                self.messages.append({
                    'role': 'assistant',
                    'content': response['response']
                })

                # Log usage
                log_usage(response['response_obj'], model)

                return response

            except Exception as e:
                last_error = e
                if self.verbose:
                    print(f"Attempt {attempt + 1}/{retry_count} failed: {e}")
                if attempt < retry_count - 1:
                    time.sleep(retry_delay * (attempt + 1) + random.uniform(0, 10) * retry_delay)

        raise last_error

    def _call_anthropic(
        self,
        messages: List,
        model: str,
        max_tokens: int,
        temperature: float,
        max_thinking_tokens: int
    ) -> Dict[str, Any]:
        """Call Anthropic API with streaming to support long requests."""
        with self.client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "enabled", "budget_tokens": max_thinking_tokens},
            temperature=temperature,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        # Extract response text
        response_text = ""
        think_text = ""

        for block in response.content:
            if hasattr(block, 'text'):
                response_text += block.text
            if hasattr(block, 'thinking'):
                think_text += block.thinking

        return {
            'response': response_text,
            'think_text': think_text,
            'response_obj': response
        }

    def reset_conversation(self):
        """Reset conversation history."""
        self.messages = []

    def set_conversation(self, messages: List):
        """Set conversation history."""
        self.messages = messages

    def get_conversation(self) -> List:
        """Get conversation history."""
        return self.messages

    def save(self, filepath: str):
        """Save LLM state to pickle."""
        save_pickle(self, filepath)

    @classmethod
    def load(cls, filepath: str) -> 'EnhancedAnthropicLLM':
        """Load LLM state from pickle."""
        return load_pickle(filepath)


# =============================================================================
# PROGRESS TRACKING
# =============================================================================

class GenerationProgress:
    """Track progress of task generation."""

    def __init__(self, output_dir: str, prefix: str):
        self.output_dir = output_dir
        self.prefix = prefix
        self.questions = []
        self.responses = []
        self.messages = []

        os.makedirs(output_dir, exist_ok=True)

    def add_result(self, question: str, response: Any, messages: List):
        """Add a generation result."""
        self.questions.append(question)
        self.responses.append(response)
        self.messages.append(messages)

        # Auto-save periodically
        save_every = int(os.environ.get("GENERATION_SAVE_EVERY", "10"))
        if save_every > 0 and len(self.questions) % save_every == 0:
            self.save()

    def save(self):
        """Save progress to files."""
        save_pickle(self.questions, os.path.join(self.output_dir, f'{self.prefix}_questions.pkl'))
        save_pickle(self.responses, os.path.join(self.output_dir, f'{self.prefix}_responses.pkl'))
        save_pickle(self.messages, os.path.join(self.output_dir, f'{self.prefix}_messages.pkl'))

    def load(self) -> int:
        """Load existing progress. Returns number of completed items."""
        questions_path = os.path.join(self.output_dir, f'{self.prefix}_questions.pkl')
        responses_path = os.path.join(self.output_dir, f'{self.prefix}_responses.pkl')
        messages_path = os.path.join(self.output_dir, f'{self.prefix}_messages.pkl')

        if os.path.exists(questions_path):
            self.questions = load_pickle(questions_path) or []
        if os.path.exists(responses_path):
            self.responses = load_pickle(responses_path) or []
        if os.path.exists(messages_path):
            self.messages = load_pickle(messages_path) or []

        return len(self.questions)

    def get_generated_task_names(self) -> List[str]:
        """Get list of generated task names for deduplication."""
        names = []
        for q in self.questions:
            name = extract_task_name_from_response(q)
            if name:
                names.append(name)
        return names


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================

def validate_task_json(content: str) -> Tuple[bool, str]:
    """
    Validate task.json content.

    Returns:
        (is_valid, error_message)
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"

    required_fields = ['id', 'description', 'hooks', 'success']
    missing = [f for f in required_fields if f not in data]

    if missing:
        return False, f"Missing required fields: {missing}"

    # Check hooks
    hooks = data.get('hooks', {})
    if not hooks.get('pre_task') or not hooks.get('post_task'):
        return False, "Missing pre_task or post_task hook"

    # Check success spec
    success = data.get('success', {})
    if success.get('mode') != 'program':
        return False, "success.mode should be 'program'"

    return True, ""


def validate_verifier_py(content: str) -> Tuple[bool, str]:
    """
    Validate verifier.py content.

    Returns:
        (is_valid, error_message)
    """
    # Check for common errors
    if 'exec_in_env' in content and 'copy_from_env' not in content:
        return False, "Uses exec_in_env without copy_from_env (exec_in_env may not be available)"

    if 'def verify_' not in content:
        return False, "No verify_* function defined"

    # Check for proper return structure
    if '"passed"' not in content and "'passed'" not in content:
        return False, "Return dict should include 'passed' key"

    return True, ""


def validate_task_files(files: Dict[str, str]) -> Dict[str, Tuple[bool, str]]:
    """
    Validate all task files.

    Returns:
        Dict mapping filename to (is_valid, error_message)
    """
    results = {}

    if 'task.json' in files:
        results['task.json'] = validate_task_json(files['task.json'])

    if 'verifier.py' in files:
        results['verifier.py'] = validate_verifier_py(files['verifier.py'])

    # Check shell scripts have shebang
    for filename in ['setup_task.sh', 'export_result.sh']:
        if filename in files:
            if not files[filename].strip().startswith('#!/bin/bash'):
                results[filename] = (False, "Missing #!/bin/bash shebang")
            else:
                results[filename] = (True, "")

    return results


# =============================================================================
# LLM FACTORY
# =============================================================================

def create_llm(
    model: str,
    verbose: bool = True
):
    """
    Create an LLM instance based on model name.

    Supported models:
    - claude-*: Anthropic Claude models (via the Anthropic API)
    - gemini-*: Google Gemini models (via litellm)

    Args:
        model: Model name/ID
        verbose: Enable verbose logging

    Returns:
        LLM instance (EnhancedAnthropicLLM or GeminiLLM)
    """
    if model.startswith('gemini'):
        if not HAS_LITELLM:
            raise ImportError("litellm required for Gemini models. Install with: pip install litellm")
        return GeminiLLM(model=model, verbose=verbose)
    else:
        # Default to Anthropic/Claude
        return EnhancedAnthropicLLM(
            model=model,
            verbose=verbose
        )


if __name__ == "__main__":
    print("Enhanced Utilities Module")
    print("=" * 50)
    print(f"\nProject root: {PROJECT_ROOT}")
    print(f"Examples dir: {EXAMPLES_DIR}")
    print(f"Env notes dir: {ENV_NOTES_DIR}")

    print("\nAvailable functions:")
    print("  - load_env_creation_notes()")
    print("  - load_verification_guidance()")
    print("  - extract_task_name_from_response(response)")
    print("  - parse_task_files(response)")
    print("  - save_task_files(folder, files)")
    print("  - validate_task_files(files)")
    print("  - create_llm(model, verbose)")

    print("\nAvailable classes:")
    print("  - EnhancedAnthropicLLM")
    print("  - GeminiLLM")
    print("  - GenerationProgress")

    print("\nSupported models:")
    print("  - claude-sonnet-4-20250514 (default)")
    print("  - gemini-3-flash-preview (with reasoning_effort='high')")
