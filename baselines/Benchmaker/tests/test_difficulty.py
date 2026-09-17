import ast
from copy import deepcopy
from itertools import product
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upstream"))
from difficulty import DifficultyCombinations, difficulty_bands


def original_combinations(attributes):
    """The upstream enumeration and stable sort, used only on small inputs."""
    bank = [[{}, 1]]
    for key in attributes:
        new_bank = []
        for value, score in attributes[key]:
            for candidate in bank:
                new_candidate = deepcopy(candidate)
                new_candidate[1] += score
                new_candidate[0][key] = value
                new_bank.append(new_candidate)
        bank = new_bank
    return [candidate[0] for candidate in sorted(bank, key=lambda x: x[1])]


class DifficultyTests(unittest.TestCase):
    def check_equivalence(self, attributes):
        expected = original_combinations(attributes)
        actual = DifficultyCombinations(attributes)
        self.assertEqual(len(actual), len(expected))
        for i, combination in enumerate(expected):
            self.assertEqual(list(actual[i].items()), list(combination.items()))
        if expected:
            self.assertEqual(actual[-1], expected[-1])
        with self.assertRaises(IndexError):
            actual[len(actual)]
        with self.assertRaises(IndexError):
            actual[-len(actual) - 1]
        upper_half = expected[len(expected) // 2:]
        bands = difficulty_bands(attributes)
        old_rng, new_rng = random.Random(42), random.Random(42)
        for i, band in enumerate(bands):
            old_band = upper_half[int(i / 10 * len(upper_half)):int((i + 1) / 10 * len(upper_half))]
            self.assertEqual(list(band), old_band)
            for _ in range(20):
                if old_band:
                    self.assertEqual(list(old_rng.choice(old_band).items()),
                                     list(new_rng.choice(band).items()))
                else:
                    with self.assertRaises(IndexError):
                        new_rng.choice(band)
        self.assertEqual(old_rng.getstate(), new_rng.getstate())

    def test_exhaustive_small_scores(self):
        for scores in product((1, 2, 3), repeat=6):
            attributes = {f"a{i}": [(f"v{j}", scores[2*i+j]) for j in range(2)]
                          for i in range(3)}
            self.check_equivalence(attributes)

    def test_ties_duplicates_empty_and_odd_sizes(self):
        for attributes in ({}, {"a": []}, {"a": [("x", 1)]},
                           {"a": [("x", 1), ("x", 1), ("y", 1)],
                            "b": [("x", 1), ("y", 1), ("z", 1)]},
                           {"a": [("x", 10), ("y", 1), ("z", 5)],
                            "b": [("x", 4), ("y", 3), ("z", 8)]}):
            self.check_equivalence(attributes)

    def test_varied_attribute_sizes(self):
        rng = random.Random(42)
        for _ in range(50):
            attributes = {f"a{i}": [(f"v{j}", rng.randint(1, 10))
                                     for j in range(rng.randint(1, 4))]
                          for i in range(rng.randint(1, 6))}
            self.check_equivalence(attributes)

    def test_large_tied_population_preserves_exact_rank(self):
        attributes = {f"a{i}": [(f"v{j}", 1) for j in range(5)] for i in range(20)}
        bands = difficulty_bands(attributes)
        total = 5**20
        half = total - total // 2
        expected_rng, actual_rng = random.Random(42), random.Random(42)
        for i, band in enumerate(bands):
            ranks = range(total // 2, total)[int(i / 10 * half):int((i + 1) / 10 * half)]
            for _ in range(100):
                rank = expected_rng.choice(ranks)
                expected = {}
                for key in attributes:
                    rank, value = divmod(rank, 5)
                    expected[key] = f"v{value}"
                self.assertEqual(list(actual_rng.choice(band).items()), list(expected.items()))
        self.assertEqual(expected_rng.getstate(), actual_rng.getstate())

    def test_generator_uses_bands_with_original_random_choice(self):
        tree = ast.parse((ROOT / "upstream/final_LLMasBenchmarkGenerator_1.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main_1_single")
        build = next(n for n in ast.walk(function) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "dif_banks" for t in n.targets))
        choose = next(n for n in ast.walk(function) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "cur_dif_attr" for t in n.targets))
        code = compile(ast.Module(body=[build, choose], type_ignores=[]), "generator_selection", "exec")
        attributes = {f"a{i}": [(f"v{j}", j + 1) for j in range(4)] for i in range(4)}
        expected = original_combinations(attributes)[128:]
        for i in range(10):
            rng = random.Random(42)
            namespace = {"attr4": attributes, "qujian": i, "random": rng,
                         "difficulty_bands": difficulty_bands}
            exec(code, namespace)
            reference_rng = random.Random(42)
            self.assertEqual(namespace["cur_dif_attr"], reference_rng.choice(
                expected[int(i/10*len(expected)):int((i+1)/10*len(expected))]))
            self.assertEqual(rng.getstate(), reference_rng.getstate())


if __name__ == "__main__":
    unittest.main()
