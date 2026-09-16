<div align="center">
    <h1>Gym-Anything: Turn Any Software into an Agent Environment</h1>
    <a href="https://cmu-l3.github.io/gym-anything"><img src="https://img.shields.io/website?down_message=down&style=for-the-badge&up_message=up&url=https%3A%2F%2Fcmu-l3.github.io%2Fgym-anything"></a>
    <a href="https://cmu-l3.github.io/gym-anything/docs/"><img src="https://img.shields.io/badge/Docs-Read-blue?style=for-the-badge&logo=readthedocs&logoColor=white"></a>
    <a href="https://arxiv.org/abs/2604.06126"><img src="https://img.shields.io/badge/arXiv-2604.06126-red.svg?style=for-the-badge"></a>
    <a href="https://cmu-l3.github.io/gym-anything/interactive_paper.html"><img src="https://img.shields.io/badge/Interactive-Paper-purple?style=for-the-badge"></a>
    <a href="https://github.com/cmu-l3/gym-anything"><img src="https://img.shields.io/badge/GitHub-Code-black?style=for-the-badge&logo=github"></a>
    <br>
</div>

<br>

Gym-Anything lets you test AI agents on real software — browsers, IDEs, medical records systems, CAD tools, and more — through a standard environment API.

## Quickstart

```bash
# 1. Install (we recommend uv: https://docs.astral.sh/uv/)
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[all]"

# 2. Check what's available on your machine, and help you set up the rest.
gym-anything doctor

# 3. Run an environment interactively
gym-anything run moodle --task enroll_student -i --open-vnc
```

## Run A Benchmark End To End

Pick an environment, pick a task, pick an agent:

```bash
gym-anything benchmark moodle --task enroll_student --agent ClaudeAgent --model claude-opus-4-6
```

This starts the Moodle environment, resets it, hands the task to the agent, lets the agent interact with the application through screenshots and mouse/keyboard actions, and runs the automatic checker when the agent finishes.

To run across many tasks at once:

```bash
gym-anything benchmark moodle --agent ClaudeAgent --model claude-opus-4-6 --split test
```

Recommended: To run with default caching for the software, which is much faster for subsequent runs:

```bash
gym-anything benchmark moodle --task enroll_student --agent ClaudeAgent --model claude-opus-4-6 --use-cache --cache-level default
```

## Three Independent Components

The framework is built around three parts that connect through shared contracts but can each be used or replaced independently:

```
                  ┌──────────────┐
                  │     Core     │
                  └──┬───────┬───┘
                   ▲ │       │ ▲
                   │ ▼       ▼ │
       ┌───────────┴─┐     ┌──┴────────────┐
       │  Benchmarks │◄───►│    Agents     │
       └─────────────┘     └───────────────┘
```

- **Core** (`src/gym_anything/`) — the runtime that starts environments, sends actions, captures observations, and runs verifiers. 
- **Benchmarks** (`benchmarks/cua_world/`) — a ready-made collection of environments and tasks. Each environment wraps a real application; each task defines a specific job, a setup script, and an automatic checker.
- **Agents** (`agents/`) — reference agent implementations (Claude, Gemini, Qwen, Kimi, and others). Bring your own or use ours.

You can use Core alone with your own environments. You can plug any agent into the benchmarks. You can write a new benchmark without touching agent code.



## Contributing

We welcome contributions — new tasks, new environments, bug fixes, and new agent implementations.

The simplest way to contribute is to add a new task to an existing environment. Each task is self-contained in its own folder with a description, a setup script, and a verifier. See the [docs on tasks and checks](https://cmu-l3.github.io/gym-anything/docs/benchmarks/tasks-verifiers/) for how these are structured.

If you want to contribute a new environment or agent, start by reading the [contributing guide](https://cmu-l3.github.io/gym-anything/docs/contributing/).

## Where To Read Next

- [Installation](https://cmu-l3.github.io/gym-anything/docs/installation/) — full setup guide with platform-specific instructions
- [Core Overview](https://cmu-l3.github.io/gym-anything/docs/core/) — how the environment API works
- [Benchmarks](https://cmu-l3.github.io/gym-anything/docs/benchmarks/) — how environments and tasks are organized
- [Agents](https://cmu-l3.github.io/gym-anything/docs/agents/) — reference agents and how to add your own
