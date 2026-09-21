"""Deterministic import of the published Benchmark-Agent questions and native self-tests."""
import ast
import hashlib
import json
from pathlib import Path

from ..authoring import benchmark_io
from ..execution.task_runtime import task_digest
from ..protocols.task_definition import EpisodeRecord, MetricResult
from ..types import BenchmarkItem, EvalDimension, EvalRun, EvalSpec, ItemResult, QcReport, TaskSuite
from . import benchmark_agent_scorer


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_helpers(upstream):
    """Extract pure native parsing functions without importing baseline model clients."""
    selections = {
        'local/self_evaluate.py': ['choice_label'],
        'utils/llm_caller.py': ['_extract_fenced_blocks', '_fix_common_json_issues',
                              '_literal_eval_fallback', '_json5_fallback', '_safe_json_loads'],
    }
    parts = ['from __future__ import annotations\nimport ast, json, re\n']
    for path, names in selections.items():
        source = (Path(upstream) / path).read_text()
        functions = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
        parts.extend(ast.get_source_segment(source, functions[name]) for name in names)
    return '\n\n'.join(parts) + '\n'


def convert_requirement(source_dir, name, *, upstream, revision):
    root = Path(source_dir).resolve()
    data_path, provenance_path = root / 'data' / f'{name}.jsonl', root / 'provenance' / f'{name}.json'
    manifest = json.loads((root / 'provenance/manifest.json').read_text())
    for path in [data_path, provenance_path]:
        if sha256(path) != manifest['files_sha256'][f'benchmark-agent/{path.relative_to(root)}']:
            raise ValueError(f'Published checksum mismatch: {path}')
    rows = [json.loads(line) for line in data_path.read_text().splitlines() if line.strip()]
    data_hash = sha256(data_path)
    provenance = json.loads(provenance_path.read_text())
    settings = provenance['selftest_config']
    helpers = native_helpers(upstream)
    namespace = {}
    exec(compile(helpers, 'native.py', 'exec'), namespace)
    choice_label = namespace['choice_label']
    subtasks = {s['id']: s for s in provenance['subtasks']}
    dimensions = [EvalDimension(id=s['id'], name=s['name'], description=s['description'],
                               approach='Benchmark-Agent native task and self-test protocol') for s in subtasks.values()]
    spec = EvalSpec(objective=provenance['requirement'], scale=len(rows), dimensions=dimensions)
    tasks, results, records = [], [], []
    for index, row in enumerate(rows):
        original = json.loads(row['original_question_json'])
        native = json.loads(row['original_selftest_json'])
        inputs, reference = json.loads(row['input_json']), json.loads(row['reference_output_json'])
        subtask = subtasks[row['subtask_id']]
        method = 'exact_choice' if subtask['answer_type'] == 'choice' and choice_label(reference.get('answer')) else 'model_judge'
        if (row['question_index'] != index or native['index'] != index
            or row['id'] != f'benchmark-agent/{name}/{index:04d}' or row['task'] != name
            or row['requirement'] != spec.objective or row['subtask_name'] != subtask['name']
            or row['answer_type'] != subtask['answer_type']
            or inputs != original['sample']['input'] or reference != original['sample']['output']
            or native['reference'] != reference or row['model_answer'] != native['prediction']
            or native['status'] != 'scored' or native['finish_reason'] != 'stop'
            or row['correct'] != native['correct'] or type(row['correct']) is not bool
            or row['scoring_method'] != method or native['method'] != method
            or native['source_idx'] != original['idx']
            or any(row[k] != original[k] or row[k] != native[k] for k in ['subtask_id', 'dataset_id'])):
            raise ValueError(f'Inconsistent exported records at {name}/{index}; refusing to infer alignment')
        if method == 'exact_choice':
            expected = choice_label(native['prediction']) == choice_label(reference['answer'])
        else:
            parsed = namespace['_safe_json_loads'](native['judge_raw'])
            if not isinstance(parsed, dict) or type(parsed.get('correct')) is not bool:
                raise ValueError(f'Invalid saved native judge output at {name}/{index}')
            expected = parsed['correct']
        if expected != native['correct']:
            raise ValueError(f'Saved score disagrees with native evaluator at {name}/{index}')
        task_id = f'benchmark-agent-{name}-{index:04d}'
        messages = [
            {'role': 'system', 'content': settings['choice_system'] if subtask['answer_type'] == 'choice' else settings['answer_system']},
            {'role': 'user', 'content': json.dumps(inputs, ensure_ascii=False)},
        ]
        component = {
            'image': 'python:3.11-slim', 'pull_image': False, 'command': ['python', '-u', 'score.py'],
            'version': 'benchmark-agent-selftest-1',
            'files': {'score.py': Path(benchmark_agent_scorer.__file__).read_text(),
                      'native.py': helpers, 'benchmark_io.py': Path(benchmark_io.__file__).read_text()},
            'config': {'method': method, 'task_input': inputs, 'judge_system': settings['judge_system']},
            'model_roles': ['judge'] if method == 'model_judge' else [],
        }
        task = BenchmarkItem(id=task_id, dimension_id=row['subtask_id'],
            task_type={'choice': 'choice', 'binary': 'generation', 'span': 'generation'}[row['answer_type']],
            content={'messages': messages}, interaction={'protocol': 'response'},
            evaluation={
                'references': [{'id': 'answer', 'kind': 'answer', 'value': reference,
                                'semantics': 'exhaustive' if method == 'exact_choice' else 'example'}],
                'metrics': [{'id': 'accuracy', 'minimum': 0, 'maximum': 1}],
                'scorers': [{'id': 'native-selftest', 'kind': 'component', 'metrics': ['accuracy'],
                            'references': ['answer'], 'component': component}],
                'scalar': {'metric': 'accuracy', 'minimum': 0, 'maximum': 1}},
            source={'kind': 'imported'},
            provenance={'repo': 'assassinlike/b635', 'revision': revision, 'native_id': row['id'],
                        'source_file': str(data_path), 'sha256': data_hash,
                        'row': index, 'native_answer_type': row['answer_type'], 'source_dataset': row['dataset_id']})
        evidence_path = f'native/{task_id}.json'
        reason = native.get('judge_reason', 'Native strict uppercase option-letter comparison.')
        episode = EpisodeRecord(task_id=task_id, task_digest=task_digest(task),
            bindings={'runtime': 'imported.Benchmark-Agent', 'target_model': settings['model'],
                      'seed': settings.get('seed')}, outputs=[native['prediction']],
            final_messages=[*messages, {'role': 'assistant', 'content': native['prediction']}],
            termination='completed', native_evidence=[evidence_path],
            metrics=[MetricResult(metric='accuracy', value=int(native['correct']), status='valid', reason=reason)])
        tasks.append(task)
        results.append(ItemResult(item_id=task_id, target_id=settings['model'], raw_response=native['prediction'],
            score=float(native['correct']), judge_reasoning=reason, episode=episode,
            execution={'imported': True, 'native_evidence': evidence_path}))
        records.append({'task_id': task_id, 'exported': row, 'question': original, 'selftest': native,
                        'messages': messages, 'subtask': subtask})
    if len(tasks) != provenance['summary']['exported_items'] or sum(r.score for r in results) != provenance['summary']['correct']:
        raise ValueError(f'Published summary disagrees with converted items: {name}')
    spec.task_types = list(dict.fromkeys(task.task_type for task in tasks))
    suite = TaskSuite(objective=spec.objective, spec=spec, dimensions=dimensions, tasks=tasks,
                      evaluation_plan=[{'id': 'native-accuracy', 'metric': 'accuracy', 'aggregation': 'mean'}])
    run = EvalRun(suite=suite, qc_report=QcReport(summary='Imported native self-tests; construction QC not rerun'), results=results)
    conversion = {'repo': 'assassinlike/b635', 'revision': revision, 'count': len(tasks),
        'source_files': {str(p): sha256(p) for p in [data_path, provenance_path]},
        'native_source_files': {str(Path(upstream)/p): sha256(Path(upstream)/p)
                                for p in ['local/self_evaluate.py', 'utils/llm_caller.py']},
        'native_helper_sha256': hashlib.sha256(helpers.encode()).hexdigest(), 'selftest_config': settings}
    return suite, run, records, conversion
