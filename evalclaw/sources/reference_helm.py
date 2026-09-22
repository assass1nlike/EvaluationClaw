"""Import HELM's rendered requests, retaining native context and metric semantics."""
from .reference_common import reference, source_tree


def helm_requests(state, run_spec, source, *, train_trial_index=0):
    method = run_spec['adapter_spec']['method']
    if method not in {'generation', 'multiple_choice_joint', 'chat'}:
        raise ValueError(f'Expected a rendered generation/chat/joint-choice HELM run, got {method}')
    if state['adapter_spec'] != run_spec['adapter_spec']:
        raise ValueError('HELM scenario state and run spec use different adapters')
    cls = run_spec['scenario_spec']['class_name']
    allowed = {
        'helm.benchmark.scenarios.ruler_qa_scenarios.RULERHotpotQAScenario',
        'helm.benchmark.scenarios.ruler_qa_scenarios.RULERSQuADScenario',
        'helm.benchmark.scenarios.infinite_bench_en_mc_scenario.InfiniteBenchEnMCScenario',
        'helm.benchmark.scenarios.infinite_bench_en_qa_scenario.InfiniteBenchEnQAScenario',
        'helm.benchmark.scenarios.infinite_bench_en_sum_scenario.InfiniteBenchEnSumScenario',
        'helm.benchmark.scenarios.openai_mrcr_scenario.OpenAIMRCRScenario',
    }
    if cls not in allowed:
        raise ValueError(f'HELM scenario is outside the selected long-context families: {cls}')
    files = ['LICENSE', 'src/helm/benchmark/run_specs/long_context_run_specs.py',
             'src/'+cls.rsplit('.', 1)[0].replace('.', '/')+'.py',
             'src/helm/benchmark/metrics/common_metric_specs.py',
             'src/helm/benchmark/metrics/evaluate_reference_metrics.py',
             'src/helm/benchmark/metrics/reference_metric.py',
             'src/helm/benchmark/metrics/metric.py',
             'src/helm/benchmark/metrics/metric_name.py',
             'src/helm/benchmark/metrics/statistic.py',
             'src/helm/benchmark/scenarios/scenario.py',
             'src/helm/common/request.py']
    for metric in run_spec['metric_specs']:
        files.append('src/'+metric['class_name'].rsplit('.', 1)[0].replace('.', '/')+'.py')
    files += source_tree(source.root, 'src/helm/benchmark/adaptation')
    tasks, seen = [], set()
    for row in state['request_states']:
        if row['train_trial_index'] != train_trial_index:
            continue
        if row.get('request_mode') not in (None, 'original') or row.get('reference_index') is not None:
            raise ValueError('Do not reinterpret likelihood/calibration requests as independent questions')
        instance, request = row['instance'], row['request']
        native_id = str(instance['id'])
        if native_id in seen:
            raise ValueError(f'Multiple requests for one HELM instance: {native_id}')
        seen.add(native_id)
        if row['prompt_truncated']:
            raise ValueError('Use an untruncated HELM export for task-quality review')
        messages = request.get('messages') or [{'role': 'user', 'content': request['prompt']}]
        if request.get('messages') and request.get('prompt'):
            raise ValueError('Ambiguous HELM input: both prompt and messages are populated')
        refs = [r for r in instance['references'] if 'correct' in r['tags']]
        if not refs:
            raise ValueError('No correct native HELM reference')
        if method == 'multiple_choice_joint':
            mapping = row.get('output_mapping')
            if not mapping or sorted(mapping.values()) != sorted(r['output']['text'] for r in instance['references']):
                raise ValueError('Joint-choice HELM tasks require the complete native label-to-option mapping')
        # A saved model result is not task content and is deliberately not imported.
        config = {'run_spec': run_spec, 'request_parameters': {k: v for k, v in request.items() if k not in {'prompt', 'messages'}},
                  'output_mapping': row.get('output_mapping'), 'extra_data': instance.get('extra_data'),
                  'train_trial_index': train_trial_index, 'num_train_instances': row['num_train_instances'],
                  'native_references': instance['references']}
        tasks.append(source.task(f'helm-{run_spec["name"]}-{native_id}', run_spec['name'], messages,
            task_type='choice' if method == 'multiple_choice_joint' else 'generation',
            references=[reference([r['output']['text'] for r in refs])],
            source_files=files, config=config, stop=request.get('stop_sequences', []),
            metrics=[{'id': 'native_metrics', 'value_type': 'object', 'direction': 'descriptive',
                      'description': 'Metrics named by the native metric_specs, including native normalization and output mapping.'}]))
    return tasks
