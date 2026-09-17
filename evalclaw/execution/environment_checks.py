"""Explicit task readiness and isolated preflight checks."""


def run_environment_checks(commands, execute):
    records = []
    for command in commands:
        result = execute(command)
        record = {"command": command, "returncode": result.returncode,
                  "stdout": result.stdout, "stderr": result.stderr}
        records.append(record)
        if result.returncode:
            raise RuntimeError(f"Environment check failed: {record}")
    return records
