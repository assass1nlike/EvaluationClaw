"""Convert pinned native reference data to the shared task-quality review format."""
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evalclaw.sources.reference_common import NativeSource, digest, read_rows
from evalclaw.sources.reference_helm import helm_requests
from evalclaw.sources.reference_livebench import livebench, select_release
from evalclaw.sources.reference_text import ifbench, mmlu_pro


def convert(entry, output, seed):
    root = Path(entry['upstream']).resolve()
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != entry['revision']:
        raise ValueError('Native evaluator checkout does not match the pinned revision')
    if subprocess.check_output(['git', '-C', str(root), 'diff', 'HEAD', '--name-only'], text=True).strip():
        raise ValueError('Native evaluator checkout has uncommitted changes')
    source = NativeSource(root, output, repo=entry['repo'], revision=revision, dataset=entry['dataset'])
    inputs = {name: Path(path).resolve() for name, path in entry['inputs'].items()}
    kind, options = entry['format'], entry.get('options', {})
    if kind == 'helm':
        state = json.loads(inputs['state'].read_text())
        spec = json.loads(inputs['run_spec'].read_text())
        tasks = helm_requests(state, spec, source, **options)
        population = len(tasks)
        if entry.get('sample_size'):
            tasks = random.Random(seed).sample(tasks, min(entry['sample_size'], len(tasks)))
    else:
        rows = read_rows(inputs['rows'])
        if kind == 'livebench':
            rows = select_release(rows, source, options['release'])
        population = len(rows)
        if entry.get('sample_size'):
            rows = random.Random(seed).sample(rows, min(entry['sample_size'], len(rows)))
        if kind == 'mmlu-pro':
            tasks = mmlu_pro(rows, read_rows(inputs['validation']), source)
        elif kind == 'ifbench':
            tasks = ifbench(rows, source)
        elif kind == 'livebench':
            tasks = livebench(rows, source, **options)
        else:
            raise ValueError(f'Unknown reference format: {kind}')
    source.save(tasks, entry['goal'], selection={'seed': seed, 'population': population,
        'sampling': 'uniform_without_replacement' if entry.get('sample_size') else 'all',
        'options': options, 'inputs': {name: {'path': str(path), 'sha256': digest(path)} for name, path in inputs.items()}})
    return len(tasks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    seed = manifest['seed']
    random.seed(seed)
    for entry in manifest['benchmarks']:
        name = entry['id']
        if Path(name).name != name or name in {'', '.', '..'}:
            raise ValueError('Benchmark id must be a directory name')
        count = convert(entry, args.output/name, seed)
        print(f'{name}: {count} tasks', flush=True)


if __name__ == '__main__':
    main()
