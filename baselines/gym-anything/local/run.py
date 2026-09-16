"""Run an official LibreOffice Writer task with DeepSeek screenshot actions."""

import argparse
import json
import os
from pathlib import Path
import random
import subprocess
from datetime import datetime, timezone

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT.parent
IMAGE = "gym-anything-local/ubuntu-gnome-highres:20260915"


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="contract_redline_generation")
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    seed_everything(args.seed)
    run_dir = ROOT / "outputs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True)
    os.chdir(run_dir)

    source = UPSTREAM / "benchmarks/cua_world/environments/libreoffice_writer_env"
    env_dir = run_dir / "environment"
    env_dir.mkdir()
    for path in source.iterdir():
        if path.name not in {"env.json", "artifacts"}:
            (env_dir / path.name).symlink_to(path, target_is_directory=path.is_dir())
    spec = json.loads((source / "env.json").read_text())
    spec["image"] = IMAGE
    spec["runner"] = "docker"
    spec["security"]["runtime"] = "runc"
    spec["recording"]["output_dir"] = str(run_dir / "episodes")
    spec["vnc"]["enable"] = True
    for mount in spec["mounts"]:
        mount["source"] = str(UPSTREAM / mount["source"])
    documents = run_dir / "documents"
    documents.mkdir(mode=0o777)
    documents.chmod(0o777)
    spec["mounts"].append({"source": str(documents),
                           "target": "/home/ga/Documents", "mode": "rw"})
    (env_dir / "env.json").write_text(json.dumps(spec, indent=2) + "\n")

    model = os.environ["DEEPSEEK_MODEL"]
    base_url = os.environ["DEEPSEEK_BASE_URL"]
    os.environ.update(
        GYM_ANYTHING_RUNNER="docker",
        GYM_ANYTHING_DOCKER_NETWORK="gym-anything-local",
        VLM_BACKEND="local",
        VLM_BASE_URL=base_url,
        VLM_MODEL=model,
        VLM_API_KEY=os.environ["DEEPSEEK_API_KEY"],
    )
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=base_url,
                    timeout=120, max_retries=2)

    import agents.agents as registry
    from agents.agents.qwen3vl import Qwen3VLAgent
    from agents.evaluation.run_single import main as evaluate
    from agents.shared.qwen_computer_use import qwen_tools_def

    class DeepSeekAgent(Qwen3VLAgent):
        def get_system_prompt(self):
            return (
                "Control the desktop using the computer_use tool. Choose exactly one "
                "next action from the screenshot, task, and previous actions. Briefly "
                "describe the action, then call the tool. When finished, call the tool "
                "with action=terminate."
            )

        def setup_custom_logger(self):
            self.save_folder_custom = str(run_dir / "agent")
            Path(self.save_folder_custom).mkdir()
            self.native_responses = []

        def build_messages(self, current_screenshot_b64):
            messages = super().build_messages(current_screenshot_b64)
            history = iter(self.native_responses[-self.history_n:])
            native = []
            for message in messages:
                if message["role"] == "assistant":
                    response = next(history)
                    native.append(response)
                    for call in response.get("tool_calls", []):
                        native.append({"role": "tool", "tool_call_id": call["id"],
                                       "content": "Action processed; see the next screenshot for the result."})
                else:
                    native.append(message)
            return native

        def llm_call(self, messages, model, temperature, top_p, top_k):
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=temperature,
                top_p=top_p, max_tokens=4096,
                extra_body={"thinking": {"type": "disabled"}},
                tools=[qwen_tools_def(tuple(self.display_resolution))],
                tool_choice={"type": "function", "function": {"name": "computer_use"}},
                parallel_tool_calls=False,
            )
            with (run_dir / "model_calls.jsonl").open("a") as handle:
                handle.write(response.model_dump_json() + "\n")
            message = response.choices[0].message
            if len(message.tool_calls or []) != 1:
                raise RuntimeError("Expected exactly one computer_use tool call")
            self.native_responses.append(message.model_dump(exclude_none=True))
            call = message.tool_calls[0].function
            action = '{"name": ' + json.dumps(call.name) + ', "arguments": ' + call.arguments + '}'
            description = message.content or "Action: " + call.arguments
            return description + "\n<tool_call>" + action + "</tool_call>"

    registry.DeepSeekAgent = DeepSeekAgent
    agent_args = {"model": model, "temperature": 0, "history_n": 3,
                  "decoding_params": {"top_p": 1}}
    config = {
        "upstream_commit": subprocess.check_output(
            ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True).strip(),
        "environment": str(source), "task": args.task, "seed": args.seed,
        "steps": args.steps, "timeout_sec": 86400,
        "image": IMAGE, "base_url": base_url, "agent": "Qwen3VLAgent",
        "docker_network": "gym-anything-local",
        "docker_runtime": "runc",
        "image_id": subprocess.check_output(
            ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
            text=True).strip(),
        "agent_args": agent_args, "max_tokens": 4096, "thinking": "disabled",
        "tool_protocol": "native function calling with official computer_use schema",
        "cache_level": "post_start", "verifier_mode": "task",
        "verifier_model": model, "api_timeout_sec": 120, "api_max_retries": 2,
        "verifier_temperature": 0.1, "verifier_top_p": 0.95,
        "verifier_max_tokens": 2048,
        "post_reset_observation_delay": 180,
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    print(f"Run directory: {run_dir}", flush=True)
    return evaluate([
        "--env_dir", str(env_dir), "--task", args.task,
        "--agent", "DeepSeekAgent", "--agent_args", json.dumps(agent_args),
        "--steps", str(args.steps), "--seed", str(args.seed),
        "--use_cache", "--cache_level", "post_start",
        "--post_reset_observation_delay", "180",
        "--vlm_backend", "local", "--vlm_base_url", base_url,
        "--vlm_model", model, "--verifier_mode", "task", "--verbose",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
