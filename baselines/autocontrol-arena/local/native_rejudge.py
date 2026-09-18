"""Apply the original unified monitor to saved trajectories, without rollouts."""

import json
import logging
import os
from pathlib import Path
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone

from configs.config_manager import ConfigManager
from src.agents.monitor import MonitorAgent
from src.agents.monitor import prompts
from src.core.types import DesignProposal
from src.orchestration.services.monitor_service import MonitorEvaluationRequest, MonitorService
from src.orchestration.services.simulation_execution_service import SimulationExecutionService


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def build_request(source, item, report_path):
    report = json.loads(report_path.read_text())
    scenario = json.loads(report_path.with_name('scenario.json').read_text())
    source_manifest = json.loads((source / 'manifest.json').read_text())
    model = source_manifest.get('target_model') or ConfigManager().load_llm_profile(
        source_manifest['profile']).model_name
    design = DesignProposal.from_dict(json.loads(
        (source / item['environment'] / 'design.json').read_text()))
    trajectory = scenario['trajectory']
    return MonitorEvaluationRequest(
        design_proposal=design,
        target_model=model,
        task_description=SimulationExecutionService._extract_task_description(design),
        action_trajectory=trajectory['turns'],
        cot_content=[t['thought'] for t in trajectory['turns'] if t.get('thought')],
        simulation_completed=trajectory['simulation_completed'],
        max_steps_reached=report['metadata']['execution_status'] == 'max_steps',
        total_tools_available=report['resource_usage']['tools']['total_available'],
    )


class RecordedMonitor(MonitorAgent):
    def _call_llm_for_json(self, prompt, component_name):
        (self.output / 'prompt.txt').write_text(prompt)
        result = super()._call_llm_for_json(prompt, component_name=component_name)
        save(self.output / 'judge.json', result)
        return result


def evaluate(source, item, report_path, output, config):
    state = {'state': 'running', 'started_at': now(), 'source_report': str(report_path)}
    save(output / 'status.json', state)
    try:
        request = build_request(source, item, report_path)
        monitor = RecordedMonitor(llm_config=config)
        monitor.output = output
        report = MonitorService().evaluate_run(monitor=monitor, request=request)
        result = report._monitor_result.to_dict()
        if result['metadata']['execution_status'] == 'evaluation_failed':
            raise RuntimeError(result['summaries']['risk_summary'])
        # These fields are not scored by the original unified prompt.
        result['scores'].update(helpfulness=None, helpfulness_evaluated=False)
        result['verdict'].update(task_success=None, failure_type=None)
        save(output / 'report.json', result)
        state['state'] = 'completed'
    except Exception as error:
        logging.exception('Native evaluation failed: %s', output)
        state.update(state='failed', error=str(error))
    state['finished_at'] = now()
    save(output / 'status.json', state)
    return state


def main():
    base = Path(sys.argv[1]).resolve()
    manifest = json.loads((base / 'manifest.json').read_text())
    # Only this supplement process uses the original prompt.
    prompts.UNIFIED_MONITOR_PROMPT = (base / 'config/native-unified.txt').read_text()
    config = asdict(ConfigManager().load_llm_profile(manifest['judge_profile']))
    os.nice(5)
    jobs = []
    for batch in manifest['batches']:
        source = Path(batch['source'])
        source_manifest = json.loads((source / 'manifest.json').read_text())
        for item in source_manifest['items']:
            jobs.append((source, item, base / batch['name'] / item['id']))
    finished = {}
    for _, _, output in jobs:
        status_path = output / 'status.json'
        if status_path.exists():
            status = json.loads(status_path.read_text())
            if status['state'] in {'completed', 'unavailable'}:
                finished[str(output.relative_to(base))] = status
    pending = {}
    with ThreadPoolExecutor(max_workers=manifest['max_workers']) as pool:
        while len(finished) < len(jobs):
            for key, future in list(pending.items()):
                if future.done():
                    finished[key] = future.result()
                    del pending[key]
            for source, item, output in jobs:
                key = str(output.relative_to(base))
                if key in finished or key in pending:
                    continue
                source_status = source / 'items' / item['id'] / 'status.json'
                if not source_status.exists():
                    continue
                status = json.loads(source_status.read_text())
                if status['state'] == 'running':
                    continue
                reports = status.get('reports', [])
                if not reports:
                    result = {'state': 'unavailable', 'reason': 'Source run has no saved report/trajectory.'}
                    save(output / 'status.json', result)
                    finished[key] = result
                elif len(pending) < manifest['max_workers']:
                    if len(reports) != 1:
                        raise ValueError(f'Expected one source report: {key}')
                    report_path = source / reports[0]['path']
                    pending[key] = pool.submit(evaluate, source, item, report_path, output, config)
            counts = dict(Counter(s['state'] for s in finished.values()))
            progress = {'updated_at': now(), 'total': len(jobs), 'counts': counts,
                        'running': len(pending), 'waiting': len(jobs)-len(finished)-len(pending)}
            save(base / 'progress.json', progress)
            if len(finished) < len(jobs):
                time.sleep(10)
    save(base / 'summary.json', {'finished_at': now(), 'results': finished})


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    main()
