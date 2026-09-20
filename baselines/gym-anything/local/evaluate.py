"""Evaluate one generated task through the official Claude Code harness."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time
from unittest.mock import patch

import numpy as np
from dotenv import dotenv_values

from agents.agents.claude_code import ClaudeCodeAgent

ROOT = Path(__file__).resolve().parents[1]


class DeepSeekClaudeCodeAgent(ClaudeCodeAgent):
    sandbox_base_image = "node:24.21.0-bookworm-slim"
    sandbox_install = "npm install -g @anthropic-ai/claude-code@2.1.229"

    def container_env(self):
        env = super().container_env()
        env.update(CLAUDE_CODE_EFFORT_LEVEL="high", DISABLE_AUTOUPDATER="1")
        for name in ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                     "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            env[name] = self.model
        return env

    def build_cli_command(self):
        logs = Path(self.save_path) / "cli_harness"
        shutil.copy2(ROOT / "local/eval_api_retry.py", logs / "api_retry.py")
        settings = '{"alwaysThinkingEnabled":true,"effortLevel":"high"}'
        command = super().build_cli_command().replace("| claude ", "| python3 /logs/api_retry.py ")
        return command + " --effort high --settings '" + settings + "'"


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    run = args.run.resolve()
    if not args.worker:
        from local.eval_docker import use_dedicated_docker
        use_dedicated_docker()
        from local.eval_runtime import BASE_CACHE, check_host, NetworkPreflightError
        while True:
            try:
                check_host()
                break
            except NetworkPreflightError:
                time.sleep(60)
        source = args.source.resolve()
        task = json.loads((source / "tasks" / args.task / "task.json").read_text())
        run.mkdir(parents=True, exist_ok=False)
        env_dir = run / "environment"
        from local.eval_setup import prepare_environment, check_mounts
        spec, permission_changes = prepare_environment(source, env_dir, run / "episodes")
        (run / "mount-permissions.json").write_text(json.dumps(permission_changes, indent=2) + "\n")
        check_mounts(spec, run / "mount-preflight.json")
        build_job = source.parents[4]
        runner = json.loads((build_job / "config.json").read_text())["runner"]
        if runner == "qemu":
            shutil.copytree(build_job / "qemu_cache", run / "qemu_cache", symlinks=True)
            base = run / "qemu_cache/base_ubuntu_gnome.qcow2"
            base.unlink()
            base.symlink_to(BASE_CACHE / base.name)
        (run / "workspace").mkdir()
        config = dict(env=source.name, source=str(source), task=args.task, seed=42, runner=runner,
                      model="deepseek-flash", thinking=True, reasoning_effort="high",
                      cli_version="2.1.229", agent="ClaudeCodeAgent",
                      max_steps=task["init"]["max_steps"], cli_timeout_sec=28800,
                      episode_timeout_sec=86400, cache_level="pre_start", use_cache=False,
                      api_retries=3, verifier_mode="task", docker_host=os.environ["DOCKER_HOST"],
                      evaluation_base=str(BASE_CACHE / "base_ubuntu_gnome.qcow2") if runner == "qemu" else None,
                      task_sha256=hashlib.sha256((source / "tasks" / args.task / "task.json").read_bytes()).hexdigest(),
                      verifier_sha256=hashlib.sha256((source / "tasks" / args.task / "verifier.py").read_bytes()).hexdigest(),
                      source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
        (run / "config.json").write_text(json.dumps(config, indent=2) + "\n")
        from seed_batch import runtime_command
        environ = dict(os.environ, PYTHONPATH=f"{ROOT / 'src'}:{ROOT}", PYTHONHASHSEED="42",
                       PATH=f"{ROOT / 'local/runtime/qemu/bin'}:{ROOT / '.venv/bin'}:{ROOT / 'local/runtime/tools'}:/usr/local/bin:/usr/bin:/bin")
        command = runtime_command(run, [str(ROOT / ".venv/bin/python"), "-u", __file__,
                                        "--run", str(run), "--worker"], environ)
        command[command.index("--name") + 1] = "ga-eval-" + hashlib.sha256(str(run).encode()).hexdigest()[:12]
        index = command.index("type=bind,src=/tmp,dst=/tmp")
        del command[index-1:index+1]
        with (run / "driver.log").open("w") as log:
            result = subprocess.run(command, env=environ, stdout=log, stderr=subprocess.STDOUT)
        (run / "exit.json").write_text(json.dumps({"returncode": result.returncode, "finished": time.time()}) + "\n")
        return result.returncode

    config = json.loads((run / "config.json").read_text())
    api = dotenv_values(ROOT / "local/.env")
    seed_everything(config["seed"])
    os.environ.update(ANTHROPIC_API_KEY=api["DEEPSEEK_API_KEY"],
                      ANTHROPIC_BASE_URL=api["DEEPSEEK_BASE_URL"].rstrip("/") + "/anthropic",
                      GYM_ANYTHING_AGENT_SANDBOX="docker", GYM_ANYTHING_RUNNER=config["runner"],
                      GYM_ANYTHING_QEMU_CACHE=str(run / "qemu_cache"),
                      GYM_ANYTHING_QEMU_WORK_DIR=str(ROOT / "local/q" / hashlib.sha256(str(run).encode()).hexdigest()[:10]),
                      GYM_ANYTHING_QEMU_SSH_KEY=str(ROOT / "local/runtime/qemu/ssh/key"),
                      VLM_BACKEND="local", VLM_MODEL=config["model"],
                      VLM_BASE_URL=api["DEEPSEEK_BASE_URL"], VLM_API_KEY=api["DEEPSEEK_API_KEY"])
    import openai
    original_client = openai.OpenAI

    def configured_client(*args, **kwargs):
        client = original_client(*args, **kwargs)
        create = client.chat.completions.create

        def configured_create(**params):
            params.update(model=config["model"], reasoning_effort="high",
                          extra_body={"thinking": {"type": "enabled"}})
            return create(**params)

        client.chat.completions.create = configured_create
        return client

    openai.OpenAI = configured_client
    os.chdir(run)
    from agents.shared.agent_sandbox import select_sandbox
    agent_args = {"model": config["model"], "timeout_sec": config["cli_timeout_sec"]}
    agent = DeepSeekClaudeCodeAgent(agent_args)
    sandbox = select_sandbox(agent.sandbox_spec(), run / "sandbox-build")
    sandbox.build()
    version = subprocess.check_output(["docker", "run", "--rm", sandbox.image_tag,
                                       "claude", "--version"], text=True)
    (run / "cli-version.txt").write_text(version)
    import agents.agents as registry
    from agents.evaluation import run_single as official
    from local.eval_setup import observe_initialization
    from contextlib import ExitStack
    evaluate = official.main
    from local.eval_runtime import RecordedDockerSandbox
    registry.DeepSeekClaudeCodeAgent = DeepSeekClaudeCodeAgent
    arguments = ["--env_dir", str(run / "environment"), "--task", config["task"],
                     "--agent", "DeepSeekClaudeCodeAgent", "--agent_args",
                     json.dumps(agent_args), "--seed", "42",
                     *( ["--use_cache"] if config["use_cache"] else [] ),
                     "--cache_level", config["cache_level"], "--verifier_mode", "task", "--verbose"]
    make_env = official._make_env
    with ExitStack() as stack:
        def observed_make_env(args):
            return stack.enter_context(observe_initialization(make_env(args), run))
        stack.enter_context(patch.object(official, "_make_env", observed_make_env))
        stack.enter_context(patch("agents.shared.cli_harness.select_sandbox", RecordedDockerSandbox))
        return evaluate(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
