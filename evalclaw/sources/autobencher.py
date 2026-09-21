"""Deterministic import of completed AutoBencher Wikipedia QA rounds."""
import ast
import hashlib
import json
from pathlib import Path

from ..authoring import benchmark_io
from ..execution.task_runtime import task_digest
from ..protocols.task_definition import EpisodeRecord, MetricResult
from ..types import BenchmarkItem, EvalDimension, EvalRun, EvalSpec, ItemResult, QcReport, TaskSuite
from . import autobencher_scorer


SYSTEM_PROMPT = 'You are a helpful AI agent.'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_judge_prefix(source):
    tree = ast.parse(Path(source).read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fast_compare_answers')
    assignment = next(n for n in function.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'context_str' for t in n.targets))
    return ast.literal_eval(assignment.value)


def convert_round(run_dir, iteration, *, upstream):
    """Preserve native inputs, reference, comparator and observed answers; never rewrite questions."""
    root, upstream = Path(run_dir).resolve(), Path(upstream).resolve()
    config = json.loads((root / 'config.json').read_text())
    prefix = root / f'wiki.{iteration}'
    paths = {name: Path(f'{prefix}.{suffix}') for name, suffix in {
        'questions': 'KI_questions.json', 'answers': 'test_taker_inference.json',
        'grades': 'compare_answers.json'}.items()}
    questions = json.loads(paths['questions'].read_text())
    answers = [json.loads(line) for line in paths['answers'].read_text().splitlines() if line.strip()]
    grades = json.loads(paths['grades'].read_text())
    if not questions or not len(questions) == len(answers) == len(grades):
        raise ValueError('Question, answer and grade files must contain the same nonzero number of rows')
    judge_prefix = native_judge_prefix(upstream / 'wiki_autobencher.py')
    hashes = {name: sha256(path) for name, path in paths.items()}
    categories = list(dict.fromkeys(q['category'] for q in questions))
    dimensions = [EvalDimension(id=f'category-{i:03d}', name=category,
        description=category, approach='AutoBencher native Wikipedia-grounded question answering')
        for i, category in enumerate(categories, 1)]
    category_ids = {d.name: d.id for d in dimensions}
    spec = EvalSpec(objective=config['theme'], scale=len(questions), dimensions=dimensions,
                    task_types=['generation'])
    tasks, results, records = [], [], []
    for row, (q, answer, grade) in enumerate(zip(questions, answers, grades), 1):
        prompt = 'Output just with the final answer to the question.\nQuestion:' + q['question'] + '\nAnswer:'
        if (any(answer.get(k) != v for k, v in q.items()) or answer.get('prompt') != prompt
                or grade['question'] != q['question'] or grade['gold_answer'] != q['gold_answer']
                or grade['test_taker_answer'] != answer['test_taker_response'] or grade['id'] != str(row)):
            raise ValueError(f'Native artifacts disagree at row {row}; refusing to guess alignment')
        task_id = f'autobencher-r{iteration:02d}-{row:05d}'
        component = {
            'image': 'python:3.11-slim', 'pull_image': False,
            'command': ['python', '-u', 'score.py'], 'version': 'autobencher-wiki-1',
            'files': {'score.py': Path(autobencher_scorer.__file__).read_text(),
                      'benchmark_io.py': Path(benchmark_io.__file__).read_text()},
            'config': {'judge_prefix': judge_prefix, 'question': q['question'],
                       'row': row, 'system_prompt': SYSTEM_PROMPT},
            'model_roles': ['judge'],
        }
        task = BenchmarkItem(id=task_id, dimension_id=category_ids[q['category']], task_type='generation',
            content={'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                                  {'role': 'user', 'content': prompt}]},
            interaction={'protocol': 'response'},
            evaluation={
                'references': [{'id': 'answer', 'kind': 'answer', 'value': q['gold_answer'], 'semantics': 'example'},
                               {'id': 'native-rubric', 'kind': 'rubric', 'value': judge_prefix}],
                'metrics': [{'id': 'accuracy', 'minimum': 0, 'maximum': 1}],
                'scorers': [{'id': 'native-judge', 'kind': 'component', 'metrics': ['accuracy'],
                            'references': ['answer', 'native-rubric'], 'component': component}],
                'scalar': {'metric': 'accuracy', 'minimum': 0, 'maximum': 1},
            },
            source={'kind': 'imported'},
            provenance={'format': 'AutoBencher Wikipedia QA', 'run_directory': str(root),
                        'iteration': iteration, 'row': row, 'native_id': q.get('id'),
                        'files': {key: str(path) for key, path in paths.items()}, 'sha256': hashes},
        )
        verdict = grade['is_correct']
        error = None if verdict in {'true', 'false'} else f'Invalid native judge verdict: {verdict!r}'
        evidence_path = f'native/{task_id}.json'
        episode = EpisodeRecord(task_id=task_id, task_digest=task_digest(task),
            bindings={'runtime': 'imported.AutoBencher', 'seed': config.get('seed'),
                      'target_model': config.get('roles', {}).get('test_taker', config['model'])},
            outputs=[answer['test_taker_response']],
            final_messages=[*(m.model_dump(mode='json') for m in task.content.messages),
                            {'role': 'assistant', 'content': answer['test_taker_response']}],
            termination='completed', native_evidence=[evidence_path],
            metrics=[MetricResult(metric='accuracy', value=None if error else int(verdict == 'true'),
                                  status='error' if error else 'valid', reason=grade['reasons'])])
        results.append(ItemResult(item_id=task_id, target_id=episode.bindings['target_model'],
            raw_response=answer['test_taker_response'], score=float(verdict == 'true'),
            judge_reasoning=grade['reasons'], error=error, episode=episode,
            execution={'native_evidence': evidence_path, 'imported': True}))
        tasks.append(task)
        records.append({'task_id': task_id, 'source_row': row, 'question': q, 'answer': answer, 'grade': grade,
                        'judge_prompt': autobencher_scorer.judge_prompt(component['config'], q['question'],
                                                                      answer['test_taker_response'], q['gold_answer'])})
    suite = TaskSuite(objective=spec.objective, spec=spec, dimensions=dimensions, tasks=tasks,
        evaluation_plan=[{'id': 'native-accuracy', 'metric': 'accuracy', 'aggregation': 'mean'}])
    run = EvalRun(suite=suite, qc_report=QcReport(summary='Imported native results; no construction QC performed'),
                  results=results, runner_artifacts={'native_files': {k: str(v) for k, v in paths.items()}})
    manifest = {'format': 'AutoBencher Wikipedia QA', 'iteration': iteration, 'count': len(tasks),
                'goal': config['theme'], 'source_files': {k: str(v) for k, v in paths.items()}, 'sha256': hashes,
                'config_sha256': sha256(root / 'config.json'),
                'upstream_commit': config.get('upstream_commit'), 'seed': config.get('seed'),
                'roles': config.get('roles'), 'model_parameters': config.get('extra_body'),
                'judge_source_sha256': sha256(upstream / 'wiki_autobencher.py'),
                'invalid_native_grades': sum(r.error is not None for r in results)}
    return suite, run, records, manifest
