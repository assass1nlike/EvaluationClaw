"""Evaluate independent questions concurrently between official adaptive rounds."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
from pathlib import Path
import time

from evaluate_fixed import judge_prefix, judge_prompt


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def stage(indices, worker, workers, save, label):
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(worker, index): index for index in indices}
        for future in as_completed(pending):
            index = pending[future]
            try:
                result = future.result()
            except Exception as error:
                errors.append((index, str(error)))
                print(f'{label} failed at question {index + 1}: {error}', flush=True)
                continue
            save(index, result)
    if errors:
        raise RuntimeError(f'{label}: {len(errors)} questions failed; successful results are cached: {errors}')


def evaluate(questions, prefix, call, settings):
    prefix = Path(prefix)
    answers_path = Path(f'{prefix}.test_taker_inference.json')
    grades_path = Path(f'{prefix}.compare_answers.json')
    if grades_path.exists():
        return json.loads(grades_path.read_text())
    checkpoint = prefix.parent / 'parallel' / prefix.name
    checkpoint.mkdir(parents=True, exist_ok=True)
    answers = {}
    for index, answer in enumerate(read_lines(answers_path)):
        assert index < len(questions) and all(answer[k] == v for k, v in questions[index].items())
        answers[index] = answer
    for row in read_lines(checkpoint / 'answers.jsonl'):
        index, answer = row['index'], row['value']
        assert all(answer[k] == v for k, v in questions[index].items())
        if index in answers:
            assert answers[index] == answer
        answers[index] = answer

    def answer_one(index):
        question = copy.deepcopy(questions[index])
        prompt = 'Output just with the final answer to the question.\nQuestion:' + question['question'] + '\nAnswer:'
        question['prompt'] = prompt
        question['test_taker_response'] = call('target', prompt, 0.01, 50)
        return question

    def progress(phase, count):
        write_json(checkpoint / 'status.json', {'phase': phase, 'completed': count, 'total': len(questions), 'time': time.time()})
        print(f'{prefix.name} {phase}: {count}/{len(questions)}', flush=True)

    with (checkpoint / 'answers.jsonl').open('a', buffering=1) as output:
        def save_answer(index, value):
            output.write(json.dumps({'index': index, 'value': value}, ensure_ascii=False) + '\n')
            answers[index] = value
            progress('answers', len(answers))
        progress('answers', len(answers))
        stage([i for i in range(len(questions)) if i not in answers], answer_one, settings['target'], save_answer, 'answers')
    ordered_answers = [answers[i] for i in range(len(questions))]
    # Keep complete existing caches byte-for-byte; materialize partial caches in original order.
    if len(read_lines(answers_path)) != len(questions):
        temporary = answers_path.with_suffix('.tmp')
        temporary.write_text(''.join(json.dumps(a, ensure_ascii=False) + '\n' for a in ordered_answers))
        temporary.replace(answers_path)

    grades = {}
    for grade in read_lines(Path(f'{prefix}.compare_answers.jsonl')):
        index = int(grade['id']) - 1
        assert grade['question'] == questions[index]['question']
        assert grade['gold_answer'] == questions[index]['gold_answer']
        assert grade['test_taker_answer'] == answers[index]['test_taker_response']
        grades[index] = grade
    for row in read_lines(checkpoint / 'grades.jsonl'):
        index, grade = row['index'], row['value']
        assert grade['question'] == questions[index]['question']
        assert grade['test_taker_answer'] == answers[index]['test_taker_response']
        if index in grades:
            assert grades[index] == grade
        grades[index] = grade
    judge_context = judge_prefix()

    def grade_one(index):
        question, answer = questions[index], answers[index]['test_taker_response']
        response = call('judge', judge_prompt(judge_context, index + 1, question, answer), 0.0, 3000)
        grade = {'id': str(index + 1), 'question': question['question'],
                 'gold_answer': question['gold_answer'], 'test_taker_answer': answer}
        grade.update({k: v for k, v in question.items() if k not in grade})
        grade.update(reasons=response.strip(), is_correct=response.strip().split('##')[-1].strip(),
                     category=answers[index].get('category', 'None'))
        if 'difficulty' in answers[index]:
            grade['difficulty'] = answers[index]['difficulty']
        return grade

    with (checkpoint / 'grades.jsonl').open('a', buffering=1) as output:
        def save_grade(index, value):
            output.write(json.dumps({'index': index, 'value': value}, ensure_ascii=False) + '\n')
            grades[index] = value
            progress('grades', len(grades))
        progress('grades', len(grades))
        stage([i for i in range(len(questions)) if i not in grades], grade_one, settings['judge'], save_grade, 'grades')
    result = [grades[i] for i in range(len(questions))]
    Path(f'{prefix}.compare_answers.jsonl').write_text(''.join(json.dumps(g, ensure_ascii=False) + '\n' for g in result))
    write_json(grades_path, result)
    progress('complete', len(result))
    return result


def run(config, directory, api_url):
    import wiki_autobencher as official
    from openai import OpenAI

    # All retries pass through the shared forwarding quotas. Long local waits allow
    # quota queues and upstream retries to finish without duplicate client requests.
    client = OpenAI(base_url=api_url, api_key='local-proxy', timeout=7200, max_retries=0)
    agent_info = ('gpt-autobencher', None, client)
    history_dict, historical_psg = [], []

    def call(role, prompt, temperature, max_tokens):
        from util import gen_from_prompt
        result = gen_from_prompt(model='gpt-autobencher-target' if role == 'target' else 'gpt-autobencher',
            tokenizer=None, prompt=[prompt], echo_prompt=False, temperature=temperature,
            max_tokens=max_tokens, service=client, terminate_by_linebreak='no', verbose=False)
        return result.completions[0].text

    try:
        for iteration in range(1, config['iterations'] + 1):
            prefix = str(directory / f'wiki.{iteration}')
            summary = official.summarize_over_history(history_dict, gold_key='gold_answer', verbose=False)
            historical_psg = official.generate_full_qa(config['theme'], agent_info, [summary], iteration,
                outfile_prefix=prefix, historical_psg=historical_psg,
                category_gen_func=official._refine_categories_targetacc_augmented,
                generate_qa_func=official.generate_long_questions, acc_target=config['acc_target'])
            questions = json.loads(Path(f'{prefix}.KI_questions.json').read_text())
            if len(questions) == 1:
                questions = questions[0]
            results = evaluate(questions, prefix, call, config['parallel'])
            history_dict.append(results)
            print(official.get_summary_of_results(results, verbose=False), flush=True)
    finally:
        client.close()
