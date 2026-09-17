"""Index difficulty combinations in the same order as upstream's stable sort."""

from bisect import bisect_right
from collections import Counter
from itertools import accumulate
from operator import index


class DifficultyCombinations:
    def __init__(self, attributes):
        self.names = tuple(attributes)
        self.values = tuple(tuple(values) for values in attributes.values())
        # The upstream parser returns integer coefficients in [1, 10].
        if any(type(score) is not int or not 1 <= score <= 10
               for values in self.values for _, score in values):
            raise ValueError("Difficulty coefficients must be integers from 1 to 10")
        self.counts = [{1: 1}]
        for values in self.values:
            counts = Counter()
            for _, score in values:
                for subtotal, count in self.counts[-1].items():
                    counts[subtotal + score] += count
            self.counts.append(counts)
        self.scores = sorted(self.counts[-1])
        self.cumulative = list(accumulate(self.counts[-1][s] for s in self.scores))

    def __len__(self):
        return self.cumulative[-1] if self.cumulative else 0

    def __getitem__(self, rank):
        rank = index(rank)
        if rank < 0:
            rank += len(self)
        if not 0 <= rank < len(self):
            raise IndexError(rank)
        bucket = bisect_right(self.cumulative, rank)
        score = self.scores[bucket]
        if bucket:
            rank -= self.cumulative[bucket - 1]
        selected = [None] * len(self.names)
        # Upstream enumerates the last attribute outermost. Stable sorting
        # retains that order within a score, including duplicate coefficients.
        for position in reversed(range(len(self.names))):
            for value, coefficient in self.values[position]:
                count = self.counts[position].get(score - coefficient, 0)
                if rank < count:
                    selected[position] = value
                    score -= coefficient
                    break
                rank -= count
        return dict(zip(self.names, selected))


class DifficultyBand:
    def __init__(self, combinations, ranks):
        self.combinations = combinations
        self.ranks = ranks

    def __len__(self):
        return len(self.ranks)

    def __getitem__(self, rank):
        return self.combinations[self.ranks[rank]]


def difficulty_bands(attributes):
    combinations = DifficultyCombinations(attributes)
    upper_half = range(len(combinations) // 2, len(combinations))
    size = len(upper_half)
    # Keep upstream's floating-point boundary calculation exactly.
    return [DifficultyBand(combinations, upper_half[int(i / 10 * size):int((i + 1) / 10 * size)])
            for i in range(10)]
