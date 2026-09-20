import ast
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from parallel_eval import evaluate
from run import ROOT


class ParallelTest(unittest.TestCase):
    def test_official_prompt_output_equivalence_and_resume(self):
        namespace = {'os': __import__('os'), 'json': json, 'copy': copy,
                     'tqdm': SimpleNamespace(tqdm=lambda x: x),
                     'defaultdict': __import__('collections').defaultdict}
        names = {'test_taker_inference', 'fast_compare_answers', 'get_summary_of_results'}
        nodes = []
        for filename in ('tool_util.py', 'wiki_autobencher.py'):
            nodes.extend(n for n in ast.parse((ROOT / 'upstream' / filename).read_text()).body
                         if isinstance(n, ast.FunctionDef) and n.name in names)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'official-functions', 'exec'), namespace)
        questions = [{'id': str(20+i), 'question': f'Question {i}?', 'gold_answer': f'Gold {i}',
                      'category': 'C', 'wiki_entity': 'W', 'difficulty': 'hard',
                      'additional_requirement': 'R'} for i in range(5)]
        captured = []
        def generator(**kwargs):
            captured.append((kwargs['model'], kwargs['prompt'][0], kwargs['temperature'], kwargs['max_tokens']))
            text = 'answer' if kwargs['model'] == 'target' else 'reason ## true'
            return SimpleNamespace(completions=[SimpleNamespace(text=text)])
        namespace['gen_from_prompt'] = generator
        with TemporaryDirectory() as directory:
            base = Path(directory)
            original_answers = namespace['test_taker_inference'](('target', None, None), copy.deepcopy(questions), str(base/'original.answers'))
            _, expected = namespace['fast_compare_answers'](copy.deepcopy(questions), original_answers, ('judge',None,None), str(base/'original'))
            calls = []
            def call(role, prompt, temperature, budget):
                calls.append((role,prompt,temperature,budget))
                return 'answer' if role == 'target' else 'reason ## true'
            result = evaluate(copy.deepcopy(questions), base/'wiki.1', call, {'target':3,'judge':2})
            namespace['get_summary_of_results'](result, gold_key='gold_answer')
            self.assertEqual(result, expected)
            self.assertCountEqual(calls, captured)
            actual_answers = [json.loads(l) for l in (base/'wiki.1.test_taker_inference.json').read_text().splitlines()]
            self.assertEqual(actual_answers, original_answers)
            calls.clear()
            evaluate(questions, base/'wiki.1', call, {'target':3,'judge':2})
            self.assertEqual(calls, [])

            # Import one original answer and one original grade, then fail a
            # different question. Other successful answers must survive the failure.
            prefix=base/'wiki.2'
            Path(f'{prefix}.test_taker_inference.json').write_text(json.dumps(original_answers[0])+'\n')
            Path(f'{prefix}.compare_answers.jsonl').write_text(json.dumps(expected[0])+'\n')
            def failing(role,prompt,temp,budget):
                if role=='target' and prompt==captured[2][1]: raise RuntimeError('transport failed')
                return call(role,prompt,temp,budget)
            with self.assertRaises(RuntimeError):
                evaluate(questions,prefix,failing,{'target':3,'judge':2})
            calls.clear()
            resumed=evaluate(questions,prefix,call,{'target':3,'judge':2})
            namespace['get_summary_of_results'](resumed,gold_key='gold_answer')
            self.assertEqual(resumed,expected)
            self.assertEqual(sum(c[0]=='target' for c in calls),1)
            self.assertEqual(sum(c[0]=='judge' for c in calls),4)


if __name__ == '__main__':
    unittest.main()

class RoundOrderTest(unittest.TestCase):
    def test_same_round_generation_and_feedback_as_official_loop(self):
        from unittest.mock import patch
        from parallel_eval import run
        tree=ast.parse((ROOT/'upstream/wiki_autobencher.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.If) and isinstance(n.test,ast.Compare))
        branch=next(n for n in main.body if isinstance(n,ast.If) and isinstance(n.test,ast.Compare)
                    and ast.unparse(n.test)=="args.exp_mode == 'autobencher'")
        with TemporaryDirectory() as directory:
            root=Path(directory)
            traces=[]
            def summary(history,**kwargs): return json.dumps(history)
            def generate(theme,agent,history,iteration,**kwargs):
                traces.append((iteration,theme,copy.deepcopy(history),copy.deepcopy(kwargs['historical_psg']),kwargs['acc_target']))
                Path(kwargs['outfile_prefix']+'.KI_questions.json').write_text(json.dumps([{'question':'A'},{'question':'B'}]))
                return [f'page-{iteration}']
            def results(*args,**kwargs):
                prefix=kwargs.get('outfile_prefix',args[1] if len(args)>1 else '')
                return [{'question':'A','is_correct':'true'},{'question':'B','is_correct':'false'}]
            refine=object();qa=object()
            namespace={'args':SimpleNamespace(num_iters=3,outfile_prefix1=str(root/'wiki.'),theme='Theme',acc_target='0.1--0.3'),
                       'summarize_over_history':summary,'generate_full_qa':generate,
                       '_refine_categories_targetacc_augmented':refine,'generate_long_questions':qa,
                       'solve_and_compare_questions':results,'get_summary_of_results':lambda *a,**k:'summary',
                       'agent_info':None,'test_taker_info':None,'evaluator_info':None,'copy':copy,'json':json}
            exec(compile(ast.Module(body=branch.body,type_ignores=[]),'official-loop','exec'),namespace)
            expected=copy.deepcopy(traces);traces.clear()
            official=SimpleNamespace(summarize_over_history=summary,generate_full_qa=generate,
                _refine_categories_targetacc_augmented=refine,generate_long_questions=qa,
                get_summary_of_results=lambda *a,**k:'summary')
            with patch.dict('sys.modules',{'wiki_autobencher':official}),patch('parallel_eval.evaluate',side_effect=results):
                run({'iterations':3,'theme':'Theme','acc_target':'0.1--0.3','parallel':{}},root,'http://localhost:1/v1')
            self.assertEqual(traces,expected)
