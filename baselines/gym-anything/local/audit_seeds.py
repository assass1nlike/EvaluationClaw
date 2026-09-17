"""Read-only inventory and syntax checks for a completed seed batch."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gym_anything.specs import TaskSpec
from gym_anything.config.validators import validate_task_spec


def audit(batch):
    reports = []
    for job in sorted(batch.iterdir()):
        if not (job / 'config.json').exists():
            continue
        config = json.loads((job / 'config.json').read_text())
        tasks = job / 'workspace/benchmarks/cua_world/environments' / config['env'] / 'tasks'
        new = sorted(p.name for p in tasks.iterdir() if p.is_dir() and p.name != '__pycache__' and p.name not in config['original_tasks'])
        manifest = tasks / 'seed_tasks.json'
        manifest_error = None
        try:
            seeds = json.loads(manifest.read_text())
        except (OSError, ValueError) as error:
            seeds = None
            manifest_error = str(error)
        report = {'software': config['software'], 'goal': config['goal'], 'env': config['env'],
                  'new_folders': new, 'seed_manifest': seeds, 'manifest_error': manifest_error,
                  'manifest_has_five_new_tasks': isinstance(seeds, list) and len(seeds) == 5
                      and len(set(seeds)) == 5 and set(seeds) <= set(new), 'tasks': []}
        for name in new:
            folder = tasks / name
            errors = []
            title = None
            for required in ['README.md', 'task.json', 'setup_task.sh', 'export_result.sh', 'verifier.py']:
                if not (folder / required).is_file():
                    errors.append(f'Missing {required}')
            try:
                raw = json.loads((folder / 'task.json').read_text())
                validate_task_spec(TaskSpec.from_dict(raw))
                title = raw.get('name') or raw.get('description')
            except Exception as error:
                errors.append(f'task.json: {error}')
            for path in sorted(folder.rglob('*')):
                if path.suffix == '.py':
                    try:
                        ast.parse(path.read_text(), filename=str(path))
                    except (SyntaxError, UnicodeError) as error:
                        errors.append(f'{path.relative_to(folder)}: {error}')
                elif path.suffix == '.sh':
                    result = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
                    if result.returncode:
                        errors.append(f'{path.relative_to(folder)}: {result.stderr.strip()}')
            hashes = {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(folder.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
            report['tasks'].append({'name': name, 'title': title, 'path': str(folder),
                                    'syntax_errors': errors, 'sha256': hashes})
        report['phases'] = [json.loads(p.read_text()) for p in sorted(job.glob('phase_*.result.json'))]
        reports.append(report)
    reports.sort(key=lambda report: (report['goal'], report['software']))
    (batch / 'audit.json').write_text(json.dumps(reports, indent=2, ensure_ascii=False) + '\n')
    lines = [
        '本轮目标：10 个软件各生成 5 道种子题，共 50 道。阶段完成与验证结果分开记录。', '',
        '| 需求 | 软件 | 新候选 | 清单内新题 | 入选题文件与语法通过 | 官方阶段 |',
        '| --- | --- | ---: | ---: | ---: | --- |',
    ]
    manifest = []
    for report in reports:
        job = batch / report['env']
        status = json.loads((job / 'status.json').read_text()) if (job / 'status.json').exists() else {}
        complete = status.get('phase') == 4 and status.get('returncode') == 0 and not (status.get('result') or {}).get('is_error', True)
        failed_phases = [phase['phase'] for phase in report['phases']
                         if phase.get('returncode') or phase.get('timeout') or (phase.get('result') or {}).get('is_error')]
        stage = '流程结束' if complete else f"第 {status.get('phase', '?')} 阶段"
        if failed_phases:
            stage += '；曾失败/超时阶段 ' + ','.join(map(str, failed_phases))
        selected = [task for task in report['tasks'] if task['name'] in (report['seed_manifest'] or [])]
        passed = sum(not task['syntax_errors'] for task in selected)
        relative = f"{report['env']}/workspace/benchmarks/cua_world/environments/{report['env']}/tasks"
        lines.append(f"| {report['goal']} | [{report['software']}]({relative}) | {len(report['tasks'])} | {len(selected)} | {passed} | {stage} |")
        for task in report['tasks']:
            manifest.append({'goal': report['goal'], 'software': report['software'], 'env': report['env'],
                             'task': task['name'], 'path': str(Path(task['path']).relative_to(batch)),
                             'in_seed_manifest': task['name'] in (report['seed_manifest'] or []),
                             'syntax_ok': not task['syntax_errors'], 'pipeline_finished': complete,
                             'all_phases_succeeded': complete and len(report['phases']) == 4 and not failed_phases,
                             'failed_phases': failed_phases})
    lines += ['', '“文件与语法通过”检查必需文件、任务配置、Python 与 shell 语法，不代表真实环境运行或评分正确性通过。',
              '每个软件目录保存原始需求、配置、四阶段输入与模型/工具日志；任务目录中的 seed_tasks.json 由官方生成流程写出。']
    (batch / 'index.md').write_text('\n'.join(lines) + '\n')
    (batch / 'tasks.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    (batch / 'seeds.json').write_text(json.dumps([task for task in manifest if task['in_seed_manifest']], indent=2, ensure_ascii=False) + '\n')
    for report in reports:
        print(report['env'], 'new=', len(report['tasks']), 'manifest=', report['manifest_has_five_new_tasks'],
              'syntax_ok=', sum(not t['syntax_errors'] for t in report['tasks']), 'phases=',len(report['phases']))
    return reports


if __name__ == '__main__':
    batch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path((ROOT / 'local/outputs/latest_seed_batch.txt').read_text().strip())
    audit(batch.resolve())
