"""Gradually admit evaluations while observing host memory pressure."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def resources(directory):
    memory = {line.split()[0].rstrip(':'): int(line.split()[1])
              for line in Path('/proc/meminfo').read_text().splitlines()}
    pressure = {line.split()[0]: dict(part.split('=') for part in line.split()[1:])
                for line in Path('/proc/pressure/memory').read_text().splitlines()}
    vm = dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    return dict(available_gib=memory['MemAvailable'] / 1024**2,
                swap_used_gib=(memory['SwapTotal'] - memory['SwapFree']) / 1024**2,
                memory_full_avg10=float(pressure['full']['avg10']),
                oom_kills=int(vm['oom_kill']), load1=os.getloadavg()[0],
                disk_free_gib=shutil.disk_usage(directory).free / 1024**3)


def container_ooms():
    result = {}
    for path in Path('/sys/fs/cgroup/system.slice').glob('docker-*.scope/memory.events.local'):
        try:
            events = dict(line.split() for line in path.read_text().splitlines())
            result[path.parent.name] = dict(oom=int(events['oom']), kills=int(events['oom_kill']))
        except FileNotFoundError:
            continue  # A finished container can disappear during this read.
    return result


def foreign_container(scope):
    container_id = scope.removeprefix('docker-').removesuffix('.scope')
    result = subprocess.run(['docker', 'inspect', '--format',
                             '{"mounts":{{json .Mounts}},"memory":{{json .HostConfig.Memory}}}',
                             container_id], capture_output=True, text=True, timeout=10)
    if result.returncode:
        return False
    info = json.loads(result.stdout)
    root = Path(__file__).resolve().parents[1]
    return info['memory'] > 0 and not any(
        Path(mount['Source']).is_relative_to(root) for mount in info['mounts'] if mount['Type'] == 'bind')


class Ramp:
    def __init__(self, maximum, interval, directory):
        self.maximum, self.interval, self.directory = maximum, interval, Path(directory)
        self.limit = min(8, maximum)
        self.changed = time.monotonic()
        self.baseline_oom = resources(directory)['oom_kills']
        self.previous_container_ooms = container_ooms()
        self.ignored_oom = 0
        self.foreign_oom_evidence = []
        self.last_log = 0
        self.state = {}

    def slots(self, active):
        now = time.monotonic()
        sample = resources(self.directory)
        current = container_ooms()
        for scope, counts in current.items():
            previous = self.previous_container_ooms.get(scope, {'oom': 0, 'kills': 0})
            delta = counts['kills'] - previous['kills']
            if delta > 0 and counts['oom'] > previous['oom']:
                try:
                    foreign = foreign_container(scope)
                except (OSError, ValueError, subprocess.SubprocessError):
                    foreign = False
                if foreign:
                    self.ignored_oom += delta
                    self.foreign_oom_evidence.append(dict(scope=scope, kills=delta, time=time.time()))
        self.previous_container_ooms = current
        reasons = []
        if sample['available_gib'] < 128:
            reasons.append('available_memory_below_128GiB')
        if sample['memory_full_avg10'] >= 1:
            reasons.append('memory_full_pressure_at_least_1_percent')
        if sample['oom_kills'] > self.baseline_oom + self.ignored_oom:
            reasons.append('gym_or_unattributed_oom')
        if sample['disk_free_gib'] < 64:
            reasons.append('disk_free_below_64GiB')
        if reasons:
            self.changed = now
        elif self.limit < self.maximum and now - self.changed >= self.interval:
            next_limit = min(self.maximum, self.limit + 8)
            if sample['available_gib'] >= 128 + max(0, next_limit - active) * 10:
                self.limit = next_limit
                self.changed = now
        # Reserve estimated headroom for new attempts; existing attempts keep running.
        admitted = min(self.limit, active + max(0, int((sample['available_gib'] - 128) / 10)))
        self.state = dict(time=time.time(), limit=self.limit, admission_limit=0 if reasons else admitted,
                          active=active, hold_reasons=reasons, ignored_foreign_oom=self.ignored_oom,
                          oom_baseline=self.baseline_oom, foreign_oom_evidence=self.foreign_oom_evidence,
                          **sample)
        if now - self.last_log >= 30:
            with (self.directory / 'resource-monitor.jsonl').open('a') as log:
                log.write(json.dumps(self.state) + '\n')
            self.last_log = now
        return self.state['admission_limit']
