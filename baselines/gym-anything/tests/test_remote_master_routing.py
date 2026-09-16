from __future__ import annotations

import asyncio
import unittest

from gym_anything.remote.master import (
    MasterConfig,
    WorkerInfo,
    WorkerRegistry,
    _infer_required_runner,
)


class InferRequiredRunnerTests(unittest.TestCase):
    def test_explicit_runner_field_wins(self) -> None:
        self.assertEqual(_infer_required_runner({"runner": "docker"}), "docker")

    def test_falls_back_to_env_spec_runner(self) -> None:
        payload = {"env_spec": {"id": "e@1", "runner": "qemu"}}
        self.assertEqual(_infer_required_runner(payload), "qemu")

    def test_returns_none_for_env_dir_without_hint(self) -> None:
        self.assertIsNone(_infer_required_runner({"env_dir": "/foo"}))

    def test_returns_none_for_non_dict(self) -> None:
        self.assertIsNone(_infer_required_runner(None))
        self.assertIsNone(_infer_required_runner("garbage"))


class SupportsRunnerTests(unittest.TestCase):
    def _make_worker(self, runners) -> WorkerInfo:
        return WorkerInfo(
            worker_id="w1",
            url="http://w1:5100",
            hostname="w1",
            port=5100,
            max_envs=2,
            metadata={"available_runners": runners} if runners is not None else {},
        )

    def test_legacy_worker_with_no_metadata_accepts_anything(self) -> None:
        worker = self._make_worker(None)
        self.assertTrue(worker.supports_runner(None))
        self.assertTrue(worker.supports_runner("qemu"))

    def test_advertised_runner_match(self) -> None:
        worker = self._make_worker(["docker", "local"])
        self.assertTrue(worker.supports_runner("docker"))
        self.assertFalse(worker.supports_runner("qemu"))

    def test_no_required_runner_always_matches(self) -> None:
        worker = self._make_worker(["docker"])
        self.assertTrue(worker.supports_runner(None))


class ReserveSlotRoutingTests(unittest.TestCase):
    """reserve_slot_for_new_env filters by advertised runners."""

    def setUp(self) -> None:
        self.registry = WorkerRegistry(MasterConfig())
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self) -> None:
        self.loop.close()
        asyncio.set_event_loop(None)

    def _seed(self, worker_id: str, runners) -> None:
        async def add():
            await self.registry.register_worker(
                worker_id=worker_id,
                url=f"http://{worker_id}:5100",
                hostname=worker_id,
                port=5100,
                max_envs=2,
                metadata={"available_runners": runners} if runners is not None else {},
            )
        self.loop.run_until_complete(add())

    def test_routes_only_to_workers_supporting_runner(self) -> None:
        self._seed("docker-worker", ["docker", "local"])
        self._seed("qemu-worker", ["qemu", "local"])

        slot = self.loop.run_until_complete(
            self.registry.reserve_slot_for_new_env(required_runner="qemu")
        )
        self.assertIsNotNone(slot)
        self.assertEqual(slot.worker_id, "qemu-worker")

    def test_returns_none_when_no_worker_supports_runner(self) -> None:
        self._seed("docker-worker", ["docker"])

        slot = self.loop.run_until_complete(
            self.registry.reserve_slot_for_new_env(required_runner="qemu")
        )
        self.assertIsNone(slot)

    def test_unrestricted_request_matches_any_worker(self) -> None:
        self._seed("docker-worker", ["docker"])
        slot = self.loop.run_until_complete(
            self.registry.reserve_slot_for_new_env(required_runner=None)
        )
        self.assertIsNotNone(slot)


if __name__ == "__main__":
    unittest.main()
