"""Preserve LiveBench release selection, prompts, tests and native agent scaffold."""
import base64
import io
import json
import pickle
import zlib

from .reference_common import json_value, native_definitions, reference, source_tree


class _DataUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise ValueError('Executable objects are not valid encoded LiveBench tests')


def decode_tests(value):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        # Native LCB releases pickle a JSON string. Never resolve pickle globals.
        decoded = _DataUnpickler(io.BytesIO(zlib.decompress(base64.b64decode(value)))).load()
        if not isinstance(decoded, str):
            raise ValueError('Expected a JSON string in encoded LiveBench tests')
        return json.loads(decoded)


def select_release(rows, source, release):
    releases = native_definitions(source.root/'livebench/common.py', ['LIVE_BENCH_RELEASES'])['LIVE_BENCH_RELEASES']
    if release not in releases:
        raise ValueError(f'Unknown native LiveBench release: {release}')
    return [r for row in rows if (r := json_value(row))['livebench_release_date'] in releases
            and r['livebench_release_date'] <= release
            and (not r['livebench_removal_date'] or r['livebench_removal_date'] > release)]


def livebench(rows, source, *, release, scaffold=None):
    files = ['LICENSE', 'livebench/common.py', 'livebench/gen_api_answer.py', 'livebench/gen_ground_truth_judgment.py']
    tasks = []
    for row in select_release(rows, source, release):
        category, name = row['category'], row['task']
        turns = row['turns']
        if not turns or any(not isinstance(t, str) for t in turns):
            raise ValueError('LiveBench requires a nonempty list of text turns')
        config = {'release': release, 'native_question': row,
                  'entrypoint': 'livebench.gen_ground_truth_judgment.play_a_match_gt'}
        refs, extra, environment = [], [], None
        interaction = {'protocol': 'response'} if len(turns) == 1 else {
            'protocol': 'dialogue', 'turns': [{'role': 'user', 'content': t} for t in turns[1:]]}
        messages = ([{'role': 'system', 'content': row['system_prompt']}] if row.get('system_prompt') else [])
        messages.append({'role': 'user', 'content': turns[0]})
        task_type = 'multi_turn' if len(turns) > 1 else 'generation'
        if category in {'agentic_coding', 'agentic_coding_v2'}:
            if scaffold is None or len(turns) != 1:
                raise ValueError('Agentic Coding requires an explicit native scaffold and one issue statement')
            required = {'org', 'repo', 'number', 'state', 'title', 'body', 'base',
                        'resolved_issues', 'fix_patch', 'test_patch'}
            if required - row.keys() or not isinstance(row.get('base'), dict) or not row['base'].get('sha'):
                raise ValueError('Agentic Coding requires the full native repository revision, patch and test record')
            import yaml
            from jinja2 import StrictUndefined, Template
            agent_config = yaml.safe_load((source.root/scaffold).read_text())
            context = {**agent_config['agent'], **agent_config.get('environment', {}),
                       **agent_config.get('model', {}), 'task': turns[0]}
            messages = [{'role': role, 'content': Template(agent_config['agent'][field], undefined=StrictUndefined).render(**context)}
                        for role, field in [('system', 'system_template'), ('user', 'instance_template')]]
            extra = source_tree(source.root, 'livebench/agentic_code_runner') + [scaffold, 'livebench/question_weights.py']
            unavailable = {'status': 'not_provided', 'unavailable_reason':
                'Native agent, environment build and test sources are preserved; no live replay binding is supplied.',
                'version': source.provenance['evaluator_revision'], 'config': {
                    'image': f'mswebench/{row["org"]}_m_{row["repo"]}:pr-{row["number"]}',
                    'native_question': row, 'scaffold': agent_config}}
            interaction = {'protocol': 'program', 'controller': unavailable}
            environment = {'type': 'tool_service', 'service': unavailable}
            config['scaffold'] = agent_config
            refs = [reference(row, name='native-instance', kind='tests', semantics='criterion')]
            task_type = 'agent'
            grader_dir = 'coding'
        elif category == 'coding':
            grader_dir = 'coding'
            if name in {'LCB_generation', 'coding_completion'}:
                refs = [reference({'public': json.loads(row['public_test_cases']),
                                   'private': decode_tests(row['private_test_cases']),
                                   'metadata': row['original_json']}, kind='tests', semantics='criterion')]
                extra = source_tree(source.root, 'livebench/lcb_runner')
            elif name in {'code_generation', 'code_completion'}:
                refs = [reference(row['tests'], kind='tests', semantics='criterion')]
                extra = source_tree(source.root, 'livebench/code_runner')
            else:
                raise ValueError(f'Unsupported native coding task: {name}')
        elif category in {'reasoning', 'data_analysis'}:
            grader_dir = category
            refs = [reference(row['ground_truth'])]
        else:
            raise ValueError(f'Unsupported LiveBench reference category: {category}')
        tasks.append(source.task(f'livebench-{row["question_id"]}', category, messages,
            references=refs, task_type=task_type, interaction=interaction, environment=environment,
            source_files=files+source_tree(source.root, f'livebench/process_results/{grader_dir}')+extra,
            config=config, metrics=[{'id': 'native_score', 'minimum': 0, 'maximum': 1}]))
    return tasks
