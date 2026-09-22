"""Native question adapters for MMLU-Pro and IFBench."""
import copy
import re

from .reference_common import native_definitions, reference


def mmlu_pro(rows, validation, source):
    path = 'evaluate_from_api.py'
    native = native_definitions(source.root/path,
        ['preprocess', 'format_example', 'extract_answer', 'extract_again', 'extract_final', 'single_request'],
        {'re': re})
    examples = native['preprocess'](copy.deepcopy(validation))
    tasks = []
    for group in native['preprocess'](copy.deepcopy(rows)).values():
        for row in group:
            if row['category'] not in examples:
                raise ValueError(f'Missing native validation examples for {row["category"]}')
            captured = []
            def capture(client, instruction, inputs):
                captured.append(instruction+inputs)
                return 'The answer is (A)'
            # Run the native formatting path without importing or calling an API client.
            native['single_request'].__globals__['call_api'] = capture
            native['single_request'](None, row, examples, [])
            if len(captured) != 1 or row['answer'] not in 'ABCDEFGHIJ'[:len(row['options'])]:
                raise ValueError('Invalid native question/reference alignment.')
            tasks.append(source.task(f'mmlu-pro-{row["question_id"]}', row['category'],
                [{'role': 'user', 'content': captured[0]}], task_type='choice',
                references=[reference(row['answer'], semantics='exhaustive')], source_files=[path, 'LICENSE'],
                metrics=[{'id': 'accuracy', 'minimum': 0, 'maximum': 1}],
                config={'entrypoint': 'evaluate_from_api.single_request/extract_answer',
                        'prompt_variant': 'native OpenAI-compatible API',
                        'validation_question_ids': [v['question_id'] for v in examples[row['category']]],
                        'response_preprocessing': "Remove '**' before native answer extraction.",
                        'native_question': row}))
    return tasks


def ifbench(rows, source):
    files = ['run_eval.py', 'evaluation_lib.py', 'ifbench/instructions.py', 'ifbench/classic_instructions.py',
             'ifbench/instructions_registry.py', 'ifbench/instructions_util.py', 'LICENSE']
    tasks = []
    for row in rows:
        if len(row['instruction_id_list']) != len(row['kwargs']):
            raise ValueError('Each IFBench instruction must retain its corresponding kwargs.')
        tasks.append(source.task(f'ifbench-{row["key"]}', 'instruction-composition',
            [{'role': 'user', 'content': row['prompt']}],
            references=[reference({'instruction_id_list': row['instruction_id_list'], 'kwargs': row['kwargs']},
                                  name='constraints', kind='rubric', semantics='criterion')],
            source_files=files, config={'entrypoint': 'run_eval.main',
                'execution_order': 'Run test_instruction_following_strict, then test_instruction_following_loose on the same InputExample, as run_eval.main does. Strict removes null kwargs in place before loose uses them.',
                'native_input': row, 'aggregation': 'Prompt accuracy averages follow_all_instructions; instruction accuracy averages individual outcomes.'},
            metrics=[{'id': f'{mode}_prompt_accuracy', 'minimum': 0, 'maximum': 1} for mode in ('strict', 'loose')]
                + [{'id': f'{mode}_instruction_outcomes', 'value_type': 'array', 'direction': 'descriptive'} for mode in ('strict', 'loose')]))
    return tasks
