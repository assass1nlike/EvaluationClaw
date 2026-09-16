"""Pass an evaluation requirement through the official task-generation pipeline."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT.parent
sys.path.insert(0, str(UPSTREAM))
README_MODULE = (
    "extras.research.task_generation.propose_and_amplify.pipeline.main_any_app_enhanced"
)


def requirement_prompt(text):
    return "\n\n## User evaluation requirement\n\n" + text


def run_readme_stage(requirement_file, argv):
    from extras.research.task_generation.propose_and_amplify.pipeline import prompt_components

    original = prompt_components.assemble_task_generation_prompt
    requirement = Path(requirement_file).read_text(encoding="utf-8")

    def assemble(*args, **kwargs):
        return original(*args, **kwargs) + requirement_prompt(requirement)

    with patch.object(prompt_components, "assemble_task_generation_prompt", assemble), \
            patch.object(sys, "argv", [README_MODULE, *argv]):
        runpy.run_module(README_MODULE, run_name="__main__")


def main(argv=None):
    from extras.research.task_generation.propose_and_amplify import method

    parser = method.build_parser()
    parser.prog = "local/generate.py"
    parser.add_argument("--requirement-file", type=Path, required=True,
                        help="UTF-8 file containing the user's evaluation requirement")
    parser.add_argument("--deepseek", action="store_true",
                        help="Use the DeepSeek service and default model from local/.env")
    parser.set_defaults(workspace=UPSTREAM, proposer_model=None, amplifier_model=None)
    args = parser.parse_args(argv)
    api_env = {}
    if args.deepseek:
        config = dotenv_values(ROOT / ".env")
        api_env = {
            "ANTHROPIC_API_KEY": config["DEEPSEEK_API_KEY"],
            "ANTHROPIC_AUTH_TOKEN": config["DEEPSEEK_API_KEY"],
            "ANTHROPIC_BASE_URL": config["DEEPSEEK_BASE_URL"].rstrip("/") + "/anthropic",
        }
        args.proposer_model = args.proposer_model or config["DEEPSEEK_MODEL"]
        args.amplifier_model = args.amplifier_model or config["DEEPSEEK_MODEL"]
    args.proposer_model = args.proposer_model or method.DEFAULT_PROPOSER_MODEL
    args.amplifier_model = args.amplifier_model or method.DEFAULT_AMPLIFIER_MODEL
    requirement = args.requirement_file.read_text(encoding="utf-8")
    if not requirement.strip():
        parser.error("--requirement-file must contain a non-empty requirement")

    output = (args.output_dir or ROOT / "outputs" / (
        "generation_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )).resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot = output / "requirement.txt"
    if snapshot.exists() and snapshot.read_text(encoding="utf-8") != requirement:
        parser.error("output directory already contains a different requirement")
    snapshot.write_text(requirement, encoding="utf-8")
    args.output_dir = output
    args.requirement_file = snapshot
    (output / f"input_{args.stage}.json").write_text(
        json.dumps(vars(args), default=str, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    original_claude = method.propose_cc.run_claude
    original_subprocess = method._run_subprocess

    def run_claude(binary, cli_args, **kwargs):
        return original_claude(binary, [
            *cli_args, "--append-system-prompt", requirement_prompt(requirement),
        ], **kwargs)

    def run_subprocess(cmd, cwd):
        if cmd[1:3] == ["-m", README_MODULE]:
            cmd = [cmd[0], str(Path(__file__).resolve()), "--readme-stage",
                   str(snapshot), *cmd[3:]]
        return original_subprocess(cmd, cwd)

    with patch.dict(os.environ, api_env), \
            patch.object(method.propose_cc, "run_claude", run_claude), \
            patch.object(method, "_run_subprocess", run_subprocess):
        return method.run_pipeline(args)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--readme-stage"]:
        run_readme_stage(sys.argv[2], sys.argv[3:])
    else:
        raise SystemExit(main())
