"""Shared, lossless packaging for established benchmark review adapters."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import shutil
from datetime import date, datetime
from pathlib import Path

from ..diagnostics import safe_name, write_json
from ..types import BenchmarkItem, EvalDimension, EvalSpec, TaskAsset, TaskSuite


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.strftime('%Y-%m-%d')
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def source_tree(root, directory):
    return [str(p.relative_to(root)) for p in sorted((root/directory).rglob('*'))
            if p.is_file() and p.suffix in {'.py', '.yaml', '.json', '.sh'}]


def native_definitions(path, names, namespace=None):
    """Load named pure helpers/literals, without importing a native API client."""
    tree = ast.parse(Path(path).read_text())
    selected = []
    found = set()
    for node in tree.body:
        name = node.name if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in names:
            selected.append(node)
            found.add(name)
    if found != set(names):
        raise ValueError(f'Native source changed: missing helpers {set(names)-found} in {path}')
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *selected], type_ignores=[])
    values = dict(namespace or {})
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), values)
    return values


def seeded_messages(messages):
    result = []
    for message in messages:
        if not isinstance(message.get('content'), str):
            raise ValueError('This text-reference adapter requires text messages; use declared assets for multimodal inputs.')
        result.append({**message, **({'origin': 'seeded_context'} if message['role'] == 'assistant' else {})})
    return result


class NativeSource:
    def __init__(self, root, output, *, repo, revision, dataset):
        if not revision or not dataset:
            raise ValueError('Pin evaluator revision and dataset provenance before conversion.')
        self.root, self.output = Path(root).resolve(), Path(output).resolve()
        self.provenance = {'evaluator_repo': repo, 'evaluator_revision': revision, 'dataset': dataset}
        self.hashes = {}
        self._assets = {}

    def assets(self, paths):
        assets = []
        for name in dict.fromkeys(paths):
            if name in self._assets:
                assets.append(self._assets[name])
                continue
            path = (self.root/name).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError(f'Native source file unavailable: {name}')
            target = self.output/'native/source'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
            checksum = digest(path)
            if digest(target) != checksum:
                raise ValueError(f'Frozen native source changed: {name}')
            self.hashes[name] = checksum
            asset = TaskAsset(id=name, path=str(target), sha256=checksum, visibility=['reviewer'])
            self._assets[name] = asset
            assets.append(asset)
        return assets

    def task(self, native_id, group, messages, *, references, source_files, config,
             metrics=None, task_type='generation', interaction=None, environment=None, stop=None):
        assets = self.assets(source_files)
        component = {
            'status': 'not_provided',
            'unavailable_reason': 'Pinned native evaluator source and configuration are available for inspection. '
                'A live EvalClaw execution binding is not supplied by this review adapter; this does not imply a native task failure.',
            'version': self.provenance['evaluator_revision'], 'assets': [a.id for a in assets], 'config': json_value(config),
        }
        metrics = metrics or [{'id': 'score', 'description': 'Native item score; see the attached evaluator.'}]
        return BenchmarkItem(id=safe_name(str(native_id)), dimension_id=safe_name(group), task_type=task_type,
            content={'messages': seeded_messages(messages), 'stop': stop or []},
            interaction=interaction or {'protocol': 'response'}, environment=environment, assets=assets,
            evaluation={'references': references, 'metrics': metrics,
                'scorers': [{'id': 'native', 'kind': 'component', 'metrics': [m['id'] for m in metrics],
                            'references': [r['id'] for r in references], 'component': component}]},
            source={'kind': 'imported'}, provenance={**copy.deepcopy(self.provenance), 'native_id': native_id},
            annotations={'execution_evidence': 'No target run or grade is inferred from source questions.'})

    def save(self, tasks, goal, *, selection):
        if not tasks or len({t.id for t in tasks}) != len(tasks):
            raise ValueError('Conversion requires nonempty tasks with unique native identifiers.')
        groups = list(dict.fromkeys(t.dimension_id for t in tasks))
        dimensions = [EvalDimension(id=g, name=g, description=g, approach='Native reference benchmark') for g in groups]
        spec = EvalSpec(objective=goal, dimensions=dimensions, scale=len(tasks),
                        task_types=list(dict.fromkeys(t.task_type for t in tasks)))
        suite = TaskSuite(objective=goal, spec=spec, dimensions=dimensions, tasks=tasks)
        write_json(self.output/'suite.json', suite.model_dump(mode='json'))
        write_json(self.output/'construction.json', {'suite': suite.model_dump(mode='json')})
        write_json(self.output/'conversion.json', {**self.provenance, 'source_sha256': self.hashes,
            'selection': selection, 'count': len(tasks), 'item_ids': [t.id for t in tasks],
            'target_rerun': False, 'live_scorer_binding': False})
        return suite


def reference(value, *, kind='answer', semantics='example', name='answer'):
    return {'id': name, 'kind': kind, 'semantics': semantics, 'value': value}


def read_rows(path):
    path = Path(path)
    if path.suffix == '.parquet':
        import pyarrow.parquet as pq
        return pq.read_table(path).to_pylist()
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError('Expected a native row array, JSONL or Parquet file.')
    return rows
