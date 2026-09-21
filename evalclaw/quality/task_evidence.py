"""A task-only view of saved execution evidence, independent of construction logs."""
from __future__ import annotations

import json
from pathlib import Path

from ..diagnostics import redact_secrets, safe_name
from ..protocols.task_view import definition_data
from ..protocols.tool import ToolResult
from .analysis_tools import (
    ANALYSER_ARTIFACT_LIST_TOOL, ANALYSER_ARTIFACT_TOOL, ANALYSER_ITEM_EVIDENCE_TOOL,
    _bounded_max_chars, _nonnegative_int, _read_text_page, _text_evidence_page,
)


def task_data(item):
    data = definition_data(item)
    # Legacy execution contracts can live in metadata. Construction assessments,
    # repair history, and resource/planning notes are not part of this view.
    runtime = {k: item.metadata[k] for k in ('agent_env', 'task_agent', 'agent_task_package')
               if k in item.metadata}
    if runtime:
        data['metadata'] = runtime
    return data


def task_evidence_tools():
    listing = ANALYSER_ARTIFACT_LIST_TOOL.model_copy(deep=True)
    listing.description = 'List only final-task files and saved target/judge execution evidence in this review.'
    reading = ANALYSER_ARTIFACT_TOOL.model_copy(deep=True)
    reading.description = 'Read a paginated final-task or execution artifact. Construction, QC, planning and analysis reports are unavailable.'
    item = ANALYSER_ITEM_EVIDENCE_TOOL.model_copy(deep=True)
    item.description = 'Read the final task, target trajectory, or native scoring evidence for one task in this review.'
    props = item.parameters['properties']
    props['kind'].update(enum=['trajectory', 'judge', 'both', 'task', 'all'],
                         description='Final task definition or original target/judge execution evidence.')
    props['scope'] = {'type': 'string', 'enum': ['main'], 'description': 'Current reviewed task set.'}
    props.pop('iteration')
    return [listing, reading, item]


class TaskEvidence:
    def __init__(self, suite, root, run=None, *, goal=None):
        self.suite = suite
        self.root = Path(root).resolve() if root is not None else None
        self.tasks = {t.id: task_data(t) for t in suite.tasks}
        if run is not None:
            rows = [r.model_dump(mode='json') for r in run.results if r.item_id in self.tasks]
        else:
            rows = []
            if self.root:
                for name in ('run.json', 'runner/run.json'):
                    path = self.root/name
                    if path.is_file():
                        rows = json.loads(path.read_text()).get('results', [])
                        break
        self.results = [self.clean(r) for r in rows if r['item_id'] in self.tasks]
        self.virtual = {'construction.json': {'suite': {'objective': goal, 'tasks': list(self.tasks.values())}},
                        'run.json': {'results': self.results}, 'runner/run.json': {'results': self.results}}
        self.files = {}
        if not self.root:
            return
        for task in suite.tasks:
            for asset in task.assets:
                self.add(Path(asset.path))
        for row in self.results:
            for prefix in ('runner', 'run'):
                directory = self.root/prefix/safe_name(row['target_id'])/safe_name(row['item_id'])
                if directory.is_dir() and directory.resolve() == directory:
                    # Only this task's runtime subtree, never the run's global logs.
                    for path in directory.rglob('*'):
                        if path.is_file() and path.resolve().is_relative_to(directory):
                            self.add(path)
                    self.virtual[str(directory.relative_to(self.root)/'item.json')] = self.tasks[row['item_id']]
            for name in (row.get('episode') or {}).get('native_evidence', []):
                path = Path(name)
                # Imported adapters declare root-relative evidence; native runners
                # use paths relative to their per-target/per-item directory above.
                if (not path.is_absolute() and path.parts and path.parts[0] == 'native'
                        and (self.root/path).resolve().is_relative_to(self.root/'native')):
                    self.add(self.root/path)

    def add(self, path):
        path = path.resolve()
        if path.is_file() and path.is_relative_to(self.root):
            relative = path.relative_to(self.root).as_posix()
            # Control-plane artifacts never become readable via an asset alias.
            if path.parts[len(self.root.parts)] not in {'analysis', 'construction', 'laaj', 'contamination'} and relative not in {
                    'construction.json', 'run.json', 'qc_report.json', 'plan.json', 'config.json'}:
                self.files[relative] = path

    def clean(self, value):
        if isinstance(value, dict):
            if (isinstance(value.get('id'), str) and value['id'] in self.tasks
                    and 'task_type' in value and any(k in value for k in ('metadata', 'provenance', 'source'))):
                return self.tasks[value['id']]
            return {k: self.clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        return value

    def trace_data(self, value):
        value = self.clean(value)
        # Native judge request logs may embed the serialized item in a JSON user
        # message. Project that envelope too; preserve raw target/judge outputs.
        if isinstance(value, dict):
            request = value.get('request', {})
            if isinstance(request, dict):
                body = request.get('body', request)
                if isinstance(body, dict):
                    for key in ('messages', 'input'):
                        messages = body.get(key, [])
                        if not isinstance(messages, list):
                            continue
                        for message in messages:
                            if isinstance(message, dict) and message.get('role') == 'user':
                                message['content'] = self.message_content(message.get('content'))
        return value

    def message_content(self, content):
        if isinstance(content, str):
            try:
                data = json.loads(content)
            except ValueError:
                return content
            cleaned = self.clean(data)
            return json.dumps(cleaned, ensure_ascii=False) if cleaned != data else content
        if isinstance(content, list):
            return [{**block, 'text': self.message_content(block['text'])}
                    if isinstance(block, dict) and isinstance(block.get('text'), str) else block
                    for block in content]
        return content

    def name(self, raw):
        path = Path(str(raw))
        if not self.root or path.is_absolute():
            raise ValueError('Use a relative path within the task evidence view.')
        resolved = (self.root/path).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError('Path is outside the task evidence view.')
        return resolved.relative_to(self.root).as_posix()

    def image_allowed(self, raw):
        try:
            return self.name(raw) in self.files
        except ValueError:
            return False

    def dispatch(self, call):
        args = call.arguments
        try:
            if call.name == 'read_item_evidence':
                return self.item(call)
            if call.name == 'list_run_artifacts':
                prefix = self.name(args.get('prefix') or '.')
                names = sorted(n for n in self.files.keys() | self.virtual.keys()
                               if prefix == '.' or n.startswith(prefix+'/'))
                offset = _nonnegative_int(args.get('offset'))
                limit = min(200, max(1, _nonnegative_int(args.get('max_entries'), default=100)))
                page = names[offset:offset+limit]
                payload = {'prefix': prefix, 'files': [{'path': n, 'size_bytes': self.files[n].stat().st_size
                    if n in self.files else len(json.dumps(self.virtual[n]).encode())} for n in page],
                    'offset': offset, 'next_offset': offset+len(page) if offset+len(page) < len(names) else None,
                    'total_files': len(names)}
            else:
                name = self.name(args.get('path') or '')
                offset, limit = _nonnegative_int(args.get('offset')), _bounded_max_chars(args.get('max_chars'))
                if name in self.virtual:
                    value = self.virtual[name]
                elif name in self.files:
                    path = self.files[name]
                    if path.suffix != '.json':
                        text, truncated, next_offset = _read_text_page(path, offset, limit)
                        return self.result(call, {'path': name, 'content': text, 'offset': offset,
                                                 'truncated': truncated, 'next_offset': next_offset})
                    try:
                        value = self.trace_data(json.loads(path.read_text()))
                    except json.JSONDecodeError:
                        text, truncated, next_offset = _read_text_page(path, offset, limit)
                        return self.result(call, {'path': name, 'content': text, 'offset': offset,
                                                 'truncated': truncated, 'next_offset': next_offset})
                else:
                    raise ValueError('This file is not final-task or target/judge execution evidence.')
                text, truncated, next_offset = _text_evidence_page(json.dumps(value, ensure_ascii=False), offset, limit)
                payload = {'path': name, 'content': text, 'offset': offset, 'truncated': truncated, 'next_offset': next_offset}
            return self.result(call, payload)
        except (OSError, ValueError, TypeError) as exc:
            return ToolResult(tool_call_id=call.id, name=call.name, content=str(exc), error='evidence_unavailable')

    def result(self, call, data):
        return ToolResult(tool_call_id=call.id, name=call.name, content=json.dumps(redact_secrets(data), ensure_ascii=False))

    def item(self, call):
        args = call.arguments
        kind, item_id = args.get('kind', 'both'), args.get('item_id')
        if args.get('scope', 'main') != 'main' or kind not in {'trajectory', 'judge', 'both', 'task', 'all'}:
            raise ValueError('Only final tasks and their execution evidence are available here.')
        if item_id not in self.tasks:
            raise ValueError('Task is outside this review.')
        row = next((r for r in self.results if r['item_id'] == item_id and r['target_id'] == args.get('target_id')), None)
        if row is None and kind != 'task':
            raise ValueError('No matching target execution record.')
        payload = {'item_id': item_id, 'target_id': args.get('target_id'), 'scope': 'main',
                   'score': row.get('score') if row else None, 'error': row.get('error') if row else None,
                   'artifact_prefix': f"runner/{safe_name(args.get('target_id'))}/{safe_name(item_id)}"}
        fields = {}
        if kind in {'task', 'all'}:
            fields['task'] = json.dumps({'task': self.tasks[item_id]}, ensure_ascii=False)
        if kind in {'trajectory', 'both', 'all'}:
            fields.update(raw_response=row.get('raw_response', ''), episode=json.dumps(row.get('episode'), ensure_ascii=False))
        if kind in {'judge', 'both', 'all'}:
            fields['judge_reasoning'] = row.get('judge_reasoning', '')
        for name, text in fields.items():
            offset = _nonnegative_int(args.get('offset'))
            page, truncated, next_offset = _text_evidence_page(text, offset, _bounded_max_chars(args.get('max_chars')))
            payload.update({name: page, name+'_offset': offset, name+'_truncated': truncated, name+'_next_offset': next_offset})
        return self.result(call, payload)
