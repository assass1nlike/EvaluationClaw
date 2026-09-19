"""Check requirement transport without model calls or environment changes."""

from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from local import generate
from extras.research.task_generation.propose_and_amplify import method
from extras.research.task_generation.propose_and_amplify.pipeline import prompt_components


def inputs(tmp_path):
    requirement = tmp_path / "goal.txt"
    requirement.write_text('Evaluate shared decisions.\n保留 "原文" 和换行。\n')
    env = tmp_path / "benchmarks/cua_world/environments/demo_env"
    (env / "tasks").mkdir(parents=True)
    return requirement, env


@pytest.mark.parametrize("deepseek", [False, True])
def test_official_pipeline_passes_requirement_and_preserves_other_commands(tmp_path, monkeypatch, deepseek):
    requirement, env = inputs(tmp_path)
    output = tmp_path / "output"
    commands, prompts = [], []
    monkeypatch.setattr(generate, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=test-key\nDEEPSEEK_BASE_URL=https://api.deepseek.com\n"
        "DEEPSEEK_MODEL=deepseek-flash\n"
    )

    def claude(binary, args, **kwargs):
        prompts.append(args)

    def subprocess(cmd, cwd):
        commands.append(cmd)
        return 0

    original = method._run_subprocess
    with patch.object(method.propose_cc, "_resolve_bin", return_value=Path(sys.executable)), \
            patch.object(method.propose_cc, "run_claude", side_effect=claude), \
            patch.object(method, "_run_subprocess", side_effect=subprocess) as launcher:
        assert generate.main([
            *(["--deepseek"] if deepseek else []),
            "--requirement-file", str(requirement), "--software", "Demo",
            "--env-dir", str(env), "--workspace", str(tmp_path),
            "--output-dir", str(output), "--amplify-count", "1",
        ]) == 0
        assert method._run_subprocess is launcher
    assert method._run_subprocess is original
    assert len(prompts) == 4  # Notes, seeds, nudge, seed manifest.
    for args in prompts:
        assert args[-2:] == ["--append-system-prompt",
                            generate.requirement_prompt(requirement.read_text())]
        if deepseek:
            assert args[args.index("--settings") + 1] == str(tmp_path / "deepseek-settings.json")
            assert args[args.index("--effort") + 1] == "high"
        else:
            assert "--settings" not in args and "--effort" not in args
    assert [cmd[1:3] for cmd in commands] == [
        [str(Path(generate.__file__).resolve()), "--readme-stage"],
        ["-m", "extras.research.task_generation.propose_and_amplify.pipeline.main_files_any_app_enhanced"],
        ["-m", "extras.research.task_generation.propose_and_amplify.pipeline.extract_tasks"],
    ]
    assert Path(commands[0][3]).read_bytes() == requirement.read_bytes()
    assert (output / "requirement.txt").read_bytes() == requirement.read_bytes()


def test_readme_stage_keeps_original_prompt_and_arguments(tmp_path):
    requirement, env = inputs(tmp_path)
    kwargs = dict(software_name="Demo", env_folder=str(env),
                  example_readmes="example text", previous_tasks=["old_task"])
    original_prompt = prompt_components.assemble_task_generation_prompt(**kwargs)
    original_argv = sys.argv
    original_builder = prompt_components.assemble_task_generation_prompt
    received = []

    def stage(module, run_name):
        assert module == generate.README_MODULE
        assert run_name == "__main__"
        assert sys.argv == [module, "--software_name", "Demo"]
        received.append(prompt_components.assemble_task_generation_prompt(**kwargs))

    with patch.object(generate.runpy, "run_module", side_effect=stage):
        generate.run_readme_stage(requirement, ["--software_name", "Demo"])
    assert received == [original_prompt + generate.requirement_prompt(requirement.read_text())]
    assert sys.argv is original_argv
    assert prompt_components.assemble_task_generation_prompt is original_builder


@pytest.mark.parametrize("existing,requirement", [(None, " \n"), ("old goal", "new goal")])
def test_invalid_or_changed_requirement_cannot_start_generation(tmp_path, existing, requirement):
    source, env = inputs(tmp_path)
    source.write_text(requirement)
    output = tmp_path / "output"
    if existing is not None:
        output.mkdir()
        (output / "requirement.txt").write_text(existing)
    with patch.object(method, "run_pipeline") as pipeline, pytest.raises(SystemExit):
        generate.main(["--requirement-file", str(source), "--software", "Demo",
                       "--env-dir", str(env), "--output-dir", str(output)])
    pipeline.assert_not_called()
