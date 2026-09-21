"""Import completed Petri audits for review, without inventing a replay policy."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

from ..diagnostics import write_json
from ..execution.task_runtime import contract_issues, task_digest
from ..protocols.task_definition import EpisodeRecord, MetricResult
from ..types import BenchmarkItem, EvalDimension, EvalRun, EvalSpec, ItemResult, QcReport, TaskSuite


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def without_nulls(value):
    """Inspect omits null message fields while Petri's transcript retains them."""
    if isinstance(value, dict):
        return {k: without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [without_nulls(v) for v in value]
    return value


def resolve_attachments(value, attachments):
    """Resolve Inspect's complete attachment references, not arbitrary substrings."""
    if isinstance(value, str) and value.startswith('attachment://'):
        return attachments[value.removeprefix('attachment://')]
    if isinstance(value, list):
        return [resolve_attachments(v, attachments) for v in value]
    if isinstance(value, dict):
        return {k: resolve_attachments(v, attachments) for k, v in value.items()}
    return value


def archive_files(path):
    with tarfile.open(path) as archive:
        result = {}
        for member in archive:
            name = PurePosixPath(member.name)
            if not member.isfile() or name.is_absolute() or '..' in name.parts or str(name) in result:
                raise ValueError(f'Invalid archive member: {member.name}')
            result[str(name)] = archive.extractfile(member).read()
        return result


def read_audit(path):
    files = archive_files(path)
    transcripts = [n for n in files if n.startswith('transcripts/') and n.endswith('.json')]
    logs = [n for n in files if n.startswith('logs/') and n.endswith('.eval')]
    if len(transcripts) != 1 or len(logs) != 1:
        raise ValueError('Each published audit must contain one transcript and one Inspect log')
    with zipfile.ZipFile(io.BytesIO(files[logs[0]])) as archive:
        samples = [n for n in archive.namelist() if n.startswith('samples/') and n.endswith('.json')]
        if len(samples) != 1:
            raise ValueError('Each audit must contain one Inspect sample')
        sample = json.loads(archive.read(samples[0]))
    return files, json.loads(files[transcripts[0]]), sample


def target_message(message):
    content = message['content']
    if isinstance(content, list):
        content = [{'type': 'text', 'text': b['text']} if b['type'] == 'text'
                   else {'type': 'json', 'data': b} for b in content]
    value = {'role': message['role'], 'content': content}
    for key in ('name', 'tool_call_id'):
        if message.get(key):
            value[key] = message[key]
    if message.get('tool_calls'):
        value['tool_calls'] = [{'id': t['id'], 'name': t['function'], 'arguments': t['arguments'], 'raw': t}
                               for t in message['tool_calls']]
    if message['role'] == 'assistant':
        value['origin'] = 'prefill' if (message.get('metadata') or {}).get('prefill') else 'seeded_context'
    return value


def convert_requirement(source_dir, requirement, output_dir, *, target_model='deepseek-flash', revision):
    """Write readable native evidence and return one task per complete adaptive audit."""
    root, output = Path(source_dir).resolve(), Path(output_dir).resolve()
    sums = dict((line.split(maxsplit=1)[1], line.split(maxsplit=1)[0])
                for line in (root / 'SHA256SUMS').read_text().splitlines() if line.strip())

    def verified(relative):
        path = root / relative
        if sha256(path) != sums[relative]:
            raise ValueError(f'Published checksum mismatch: {relative}')
        return path

    data = verified(f'data/{target_model}.jsonl')
    rows = [json.loads(line) for line in data.read_text().splitlines() if line.strip()]
    rows = [r for r in rows if r['requirement_line'] == requirement]
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Missing or duplicate audit records')
    source_path = verified(f'provenance/{target_model}/source.tar.gz')
    source_files = archive_files(source_path)
    # Only the audit mechanism and the requirement scorer are part of this review.
    code_paths = {
        'source/requirement_judge.py', 'source/auditor_prompt.py',
        'source/upstream/src/petri/solvers/auditor_agent.py',
        'source/upstream/src/petri/solvers/prompts.py',
        'source/upstream/src/petri/tools/tools.py', 'source/upstream/src/petri/tools/util.py',
        'source/upstream/src/petri/transcript/transcript.py',
        'source/upstream/src/petri/formatting/messages.py',
        'source/upstream/src/petri/stores.py', 'source/upstream/src/petri/types.py',
    }
    code = {n: b.decode() for n, b in source_files.items() if n in code_paths}
    goal = rows[0]['requirement']
    dimension = EvalDimension(id=f'D{requirement}', name=f'D{requirement}', description=goal,
                              approach='Native Petri adaptive audit, all branches retained')
    spec = EvalSpec(objective=goal, scale=len(rows), dimensions=[dimension], task_types=['agent'])
    tasks, results, checks = [], [], []
    for row in rows:
        relative = str(PurePosixPath(row['artifact_path']).relative_to('petri'))
        archive = verified(relative)
        if sha256(archive) != row['artifact_sha256']:
            raise ValueError('Index and archive checksums disagree')
        files, transcript, sample = read_audit(archive)
        config = json.loads(files['config.json'])
        summary = json.loads(files['summary.json'])
        judgment = json.loads(files['judgment.json'])
        resolve = lambda value: resolve_attachments(value, sample.get('attachments', {}))
        store = {key: resolve(sample['store'][key]) for key in
                 ['RequirementJudgeStore:messages', 'AuditStore:target']}
        primary_messages = store['RequirementJudgeStore:messages']
        primary_input = json.loads(primary_messages[1]['content'])
        primary = judgment['judgment']
        if (row['requirement'] != goal or files['instruction.txt'].decode().strip() != goal
                or row['id'] != f"petri/{target_model}/requirement-{requirement:02d}/epoch-{row['epoch']:02d}"
                or config != json.loads(row['config_json']) or config['seed'] != row['seed']
                or config['models']['target'].split('/', 1)[1] != target_model
                or judgment != json.loads(row['judgment_json'])
                or primary['score'] != row['performance_score']
                or summary['scores']['performance'] != primary['score']
                or primary_input['requirement'] != goal
                or primary_input['rubric'] != files['rubric.txt'].decode().strip()
                or primary_messages[0]['content'] != files['judge_prompt.txt'].decode()
                or primary['status'] != 'scored'
                or not 1 <= primary['score'] <= 10
                or resolve(sample['scores']['requirement_judge']['metadata']['judgment']) != primary
                or without_nulls(transcript['target_messages']) != without_nulls(store['AuditStore:target']['messages'])):
            raise ValueError(f'Inconsistent published audit: {row["id"]}')

        task_id = f'petri-{target_model}-d{requirement:02d}-e{row["epoch"]:02d}'
        folder = output / 'native' / task_id
        folder.mkdir(parents=True, exist_ok=False)
        # Full packages stay outside the judge's artifact root: they also contain
        # supplementary alignment ratings, which are not part of this evaluation.
        for name in ['instruction.txt', 'rubric.txt', 'judge_prompt.txt', 'judgment.json', 'auditor_prompt.txt']:
            if name in files:
                (folder / name).write_bytes(files[name])
        audit_config = {k: v for k, v in config.items() if k in {
            'models', 'generation', 'seed', 'max_turns', 'allow_prefill', 'prefill_mode',
            'auditor_prompt_variant', 'versions', 'commit', 'workspace_commit', 'judge_parse_attempts'}}
        write_json(folder / 'audit-config.json', audit_config)
        write_json(folder / 'transcript.json', {
            **transcript, 'metadata': {k: v for k, v in transcript.get('metadata', {}).items() if k != 'judge_output'}})
        write_json(folder / 'requirement-judge.json', primary_messages)
        # This is the exact branch-aware input seen by the requirement judge.
        (folder / 'target-history.txt').write_text(primary_input['transcript'])
        calls = [resolve(e) for e in sample['events'] if e['event'] == 'model' and e.get('role') == 'target']
        auditor = next(resolve(e) for e in sample['events'] if e['event'] == 'model' and e.get('role') == 'auditor')
        if not calls or any(not c['output']['choices'] for c in calls):
            raise ValueError('Missing target calls or outputs')
        write_json(folder / 'target-calls.json', calls)
        write_json(folder / 'auditor-calls.json', [resolve(e) for e in sample['events']
                   if e['event'] == 'model' and e.get('role') == 'auditor'])
        write_json(folder / 'auditor-initial-request.json', auditor)
        write_json(folder / 'native-implementation.json', code)
        target_output = [c['output']['choices'][0]['message'] for c in calls]
        outputs = {m['id']: m for m in target_output}
        for message in transcript['target_messages']:
            if ((message.get('metadata') or {}).get('source') == 'Target'
                    and without_nulls(message) != without_nulls(outputs.get(message['id']))):
                raise ValueError('Target transcript message does not match an actual target model response')

        assets = []
        for path in sorted(folder.rglob('*')):
            if path.is_file() and path.suffix in {'.json', '.txt', '.md'}:
                assets.append({'id': str(path.relative_to(folder)), 'path': str(path),
                               'visibility': ['reviewer'], 'sha256': sha256(path)})
        unavailable = {
            'status': 'not_provided',
            'unavailable_reason': 'The native Petri implementation and completed audit evidence are supplied for review; an EvalClaw live replay adapter is not provided. This is not a failure of the recorded audit.',
        }
        controller = {**unavailable, 'config': {
            'audit_config': audit_config, 'initial_auditor_messages': auditor['input'],
            'auditor_tools': auditor['tools']}}
        metric_defs = [{'id': 'performance', 'minimum': 1, 'maximum': 10,
                        'description': 'Requirement-based performance judgment; descriptive rating, not accuracy.'}]
        task = BenchmarkItem(id=task_id, dimension_id=dimension.id, task_type='agent',
            content={'messages': [target_message(m) for m in calls[0]['input']]},
            interaction={'protocol': 'program', 'controller': controller,
                         'participants': [{'id': 'target', 'role': 'target'}]},
            assets=assets,
            annotations={'review_scope': 'One completed adaptive audit including every branch, not a static question or a replay against a new target.',
                'evidence': {'target_history': 'target-history.txt', 'exact_target_requests_and_tools': 'target-calls.json',
                             'full_auditor_and_branch_events': 'transcript.json',
                             'requirement_judge': 'requirement-judge.json'},
                'attribution': 'Target-history includes auditor inputs, simulated tool responses and branch markers. Only responses in target-calls.json originate from the target; preserve prefill attribution.',
                'native_status': summary['status'], 'recoverable_tool_errors': summary['tool_errors']},
            evaluation={'references': [{'id': 'requirement', 'kind': 'rubric', 'value': {'requirement': goal, 'rubric': primary_input['rubric']}}],
                'metrics': metric_defs,
                'scorers': [{'id': 'requirement-judge', 'kind': 'component', 'metrics': ['performance'], 'references': ['requirement'],
                             'component': {**unavailable, 'files': {'requirement_judge.py': code['source/requirement_judge.py'],
                                                                  'judge_prompt.txt': files['judge_prompt.txt'].decode()}}}],
                'scalar': {'metric': 'performance', 'minimum': 1, 'maximum': 10}},
            source={'kind': 'imported'},
            provenance={'repo': 'assassinlike/b635', 'revision': revision, 'native_id': row['id'],
                        'artifact': relative, 'sha256': row['artifact_sha256'], 'epoch': row['epoch'], 'seed': row['seed']})
        issues = contract_issues(task)
        if issues:
            raise ValueError(f'Invalid imported task contract {task_id}: {issues}')
        metrics = [MetricResult(metric='performance', value=primary['score'], reason=primary['reason'], raw=primary)]
        evidence = [str(Path(a['path']).relative_to(output)) for a in assets]
        episode = EpisodeRecord(task_id=task_id, task_digest=task_digest(task),
            bindings={'runtime': 'imported.Petri', 'target_model': target_model, 'seed': row['seed'],
                      'audit_config': audit_config},
            initial_state={'tools': calls[0]['tools']}, final_state={'tools': store['AuditStore:target']['tools']},
            outputs=target_output, final_messages=transcript['target_messages'],
            artifacts={'target_calls': str((folder/'target-calls.json').relative_to(output)),
                       'requirement_judgment': str((folder/'judgment.json').relative_to(output)),
                       'native_transcript': str((folder/task.annotations['evidence']['full_auditor_and_branch_events']).relative_to(output)),
                       'note': 'Native edit history is authoritative for branches; no synthetic linear event timeline is generated.'},
            termination='completed', metrics=metrics, native_evidence=evidence)
        tasks.append(task)
        results.append(ItemResult(item_id=task_id, target_id=target_model,
            raw_response=json.dumps(target_output, ensure_ascii=False), score=(primary['score']-1)/9,
            judge_reasoning=json.dumps(primary, ensure_ascii=False), episode=episode,
            execution={'imported': True, 'native_status': summary['status'], 'native_exit_code': row['exit_code'],
                       'tool_errors': summary['tool_errors'],
                       'judge_errors': {k: v for k, v in summary['judge_errors'].items() if k == 'requirement_judge'}}))
        checks.append({'id': task_id, 'target_calls': len(calls), 'native_events': len(transcript['events']),
                       'tool_errors': len(summary['tool_errors']), 'performance': primary['score']})
    suite = TaskSuite(objective=goal, spec=spec, dimensions=[dimension], tasks=tasks,
                      evaluation_plan=[{'id': 'native-performance', 'metric': 'performance', 'aggregation': 'mean'}])
    run = EvalRun(suite=suite, qc_report=QcReport(summary='Imported completed audits; no construction QC or target rerun'), results=results)
    return suite, run, {'repo': 'assassinlike/b635', 'revision': revision, 'count': len(tasks),
                        'source_sha256': {str(data): sha256(data), str(source_path): sha256(source_path)},
                        'audits': checks, 'replay_supported': False}
