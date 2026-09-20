"""Check all ten software mount copies as the actual desktop ga user."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

from local.eval_docker import use_dedicated_docker
from local.eval_setup import prepare_environment, check_mounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    use_dedicated_docker()
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for manifest in sorted(args.source.resolve().glob('*_env/workspace/benchmarks/cua_world/environments/*/tasks/seed_tasks.json')):
        source = manifest.parent.parent
        if source.name != source.parents[4].name:
            continue
        directory = output / source.name
        directory.mkdir()
        before = {str(p.relative_to(source)): (p.stat().st_mode, hashlib.sha256(p.read_bytes()).hexdigest())
                  for p in source.rglob('*') if p.is_file() and 'artifacts' not in p.relative_to(source).parts}
        spec, changes = prepare_environment(source, directory / 'environment', directory / 'episodes')
        check_mounts(spec, directory / 'guest-readability.json')
        for name, (mode, digest) in before.items():
            assert (source / name).stat().st_mode == mode
            assert hashlib.sha256((source / name).read_bytes()).hexdigest() == digest
            if name != 'env.json':
                assert hashlib.sha256((directory / 'environment' / name).read_bytes()).hexdigest() == digest
        (directory / 'permission-changes.json').write_text(json.dumps(changes, indent=2) + '\n')
        rows.append(dict(env=source.name, file_count=len(before), permissions_adjusted=len(changes),
                         source_unchanged=True, file_contents_preserved=True, ga_readable=True))
        shutil.rmtree(directory / 'environment')
        print(source.name, 'passed', flush=True)
    assert len(rows) == 10
    (output / 'verification.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
