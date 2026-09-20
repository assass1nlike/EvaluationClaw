import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rate_limit import RateLimit


def request_slots(path, ready, results):
    limiter = RateLimit(Path(path), 5, window=0.1)
    ready.wait()
    results.put([limiter.acquire() for _ in range(8)])


class RateLimitTest(unittest.TestCase):
    def test_eight_processes_share_rolling_window_and_resume(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'rate.json'
            ctx = multiprocessing.get_context('spawn')
            ready, results = ctx.Event(), ctx.Queue()
            workers = [ctx.Process(target=request_slots, args=(str(path), ready, results)) for _ in range(8)]
            for worker in workers:
                worker.start()
            ready.set()
            times = [t for _ in workers for t in results.get(timeout=20)]
            for worker in workers:
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, 0)
            # A newly constructed limiter must retain earlier workers' reservations.
            times.extend(RateLimit(path, 5, window=0.1).acquire() for _ in range(6))
            times.sort()
            self.assertEqual(len(times), 70)
            for earlier, later in zip(times, times[5:]):
                self.assertGreaterEqual(later - earlier, 0.1)


if __name__ == '__main__':
    unittest.main()
