# Environment Structure Guide

## Directory Layout

Every environment follows this standard structure:

```
benchmarks/cua_world/environments/<env_name>/
├── env.json                    # Environment specification
├── README.md                   # Documentation
├── scripts/
│   ├── install_<app>.sh        # pre_start hook - installs application
│   └── setup_<app>.sh          # post_start hook - configures app
├── config/                     # Optional config files to copy into container
├── tasks/
│   └── <task_name>/
│       ├── task.json           # Task specification
│       ├── verifier.py         # Stub verifier (VLM verification is external)
│       └── setup_task.sh       # pre_task hook — ensures correct start state
└── utils/                      # Optional utilities
```

## env.json Structure

Key fields in env.json:

```json
{
  "id": "<env_name>@<version>",
  "version": "<version>",
  "base": "ubuntu-gnome-systemd_highres",  // Standard desktop preset
  "description": "...",
  "resources": {
    "cpu": 4,
    "mem_gb": 4,
    "gpu": 0,
    "net": true  // Required for apps that need internet
  },
  "observation": [
    {"type": "rgb_screen", "fps": 10, "resolution": [1920, 1080], "inline": false}
  ],
  "action": [
    {"type": "mouse"},
    {"type": "keyboard"}
  ],
  "synchronous": true,
  "step_cycle_ms": 200,
  "security": {
    "user": "root",
    "privileged": true,
    "use_systemd": true,
    "runtime": "sysbox-runc"
  },
  "mounts": [
    {"source": "benchmarks/cua_world/environments/<env_name>/scripts", "target": "/workspace/scripts", "mode": "ro"},
    {"source": "benchmarks/cua_world/environments/<env_name>/tasks", "target": "/workspace/tasks", "mode": "ro"}
  ],
  "hooks": {
    "pre_start": "/workspace/scripts/install_<app>.sh",
    "post_start": "/workspace/scripts/setup_<app>.sh"
  },
  "user_accounts": [
    {
      "name": "<username>",
      "password": "<password>",
      "permissions": {
        "sudo": true,
        "sudo_nopasswd": true,
        "groups": ["sudo", "audio", "video", "input"],
        "env_vars": {"DISPLAY": ":1"}
      }
    }
  ]
}
```

## Task Structure

Each task.json should include:

```json
{
  "id": "<task_name>@<version>",
  "version": "1.0",
  "env_id": "<env_name>@<version>",
  "description": "...",
  "init": {
    "timeout_sec": 120,
    "max_steps": 10,
    "reward_type": "sparse"
  },
  "hooks": {
    "pre_task": "/workspace/tasks/<task_name>/setup_task.sh"
  },
  "success": {
    "mode": "program",
    "spec": {
      "program": "verifier.py::check_function_name"
    }
  }
}
```

