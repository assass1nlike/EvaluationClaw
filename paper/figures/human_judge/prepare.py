"""Extract verbatim, explicitly bounded UI examples from the frozen review batch."""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def excerpt(text, limit):
    if len(text) <= limit:
        return text
    cut = text.rfind(' ', 0, limit)
    return text[:cut] + '\n[Excerpt; continued in the full record.]'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('comparisons', type=Path)
    args = parser.parse_args()
    pairs = {p['id']: p for p in json.loads(args.comparisons.read_text())['pairs']}
    selection = [('choice', 'knowledge-08'), ('dialogue', 'instruction-following-02'),
                 ('agent', 'data-analysis-03')]
    examples = []
    for name, pair_id in selection:
        pair = pairs[pair_id]
        candidates = []
        for side, candidate in enumerate(pair['candidates']):
            task = candidate['task']
            prompt = task.get('prompt')
            if not prompt:
                prompt = '\n\n'.join(m['content'] for m in task['content']['messages'] if m['role']=='user')
            response = candidate['response']['final_response']
            rubric = next(s['content'] for s in candidate['sections'] if s['title']=='参考答案与评分规则')
            sections = []
            if side == 1:
                reference = next(r['value'] for r in rubric['evaluation']['references'] if r['id']=='answer')
                sections.append({'title':'Recorded reference answer', 'content':reference})
            elif name == 'choice':
                prompt += '\n\n' + '\n'.join(f"{c['id']}. {c['text']}" for c in task['choices'])
                sections.append({'title':'Recorded answer key', 'content':', '.join(rubric['correct_choice_ids'])})
            elif name == 'dialogue':
                turns = json.loads(response)
                # Preserve original dialogue roles and messages. These are selected
                # turns, not a reconstruction of the complete conversation.
                final_lines = turns[5]['content'].splitlines()
                response = ('User (turn 3; excerpt):\n' + excerpt(turns[4]['content'],155)
                            + '\n\nAssistant (turn 3; excerpt):\n[Entries 1–4 omitted here.]\n'
                            + '\n'.join(final_lines[-3:]))
                sections.append({'title':'Scoring rubric (excerpt)', 'content':excerpt(rubric['rubric'],260)})
                sections.append({'title':'Dialogue policy and all turns', 'content':'Available in the complete task and execution records.'})
                prompt = excerpt(prompt,180)
            elif name == 'agent':
                prompt = excerpt(prompt,190)
                response = '\n'.join(response.splitlines()[:4]) + '\n[Further output fields in the full response.]'
                sections.append({'title':'Environment and grading (excerpt)', 'content':excerpt(rubric['rubric'],140)})
            artifacts = []
            if name == 'agent' and side == 0:
                # The two displayed attachments are real files in the source export.
                for index, filename in enumerate(('t7_edge_a.log','t7_edge_b.log')):
                    original = next(a for a in candidate['artifacts'] if a['label'].endswith(filename))
                    artifacts.append({'index':index,'label':filename,
                                      'bytes':(args.comparisons.parent/original['path']).stat().st_size})
                sections.append({'title':'Full trace, outputs and grader files',
                                 'content':'Available in the complete task and execution records.'})
            candidates.append({'kind':task['task_type'],'task':prompt,'response':response,
                               'sections':sections,'artifacts':artifacts})
        # Vary sides between illustrations; do not encode a preferred candidate.
        if name == 'dialogue':
            candidates.reverse()
        examples.append({'name':name,'source_pair_id':pair_id,'requirement':pair['requirement'],
                         'candidates':candidates})
    (HERE/'examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
