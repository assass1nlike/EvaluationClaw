from __future__ import annotations

import importlib
import unittest
from unittest import mock


class RemoteModuleLayoutTests(unittest.TestCase):
    def test_core_remote_modules_import(self) -> None:
        worker = importlib.import_module("gym_anything.remote.worker")
        master = importlib.import_module("gym_anything.remote.master")
        dashboard = importlib.import_module("gym_anything.remote.dashboard_app")
        monitoring = importlib.import_module("gym_anything.remote.monitoring")

        self.assertTrue(callable(getattr(worker, "main", None)))
        self.assertTrue(callable(getattr(master, "main", None)))
        self.assertTrue(callable(getattr(dashboard, "main", None)))
        self.assertTrue(callable(getattr(monitoring, "get_metrics_collector", None)))


class WorkerKvmBackcompatTests(unittest.TestCase):
    """The standalone KVM probe was moved to gym_anything.doctor.

    The worker re-exports ``check_kvm_access`` so older callers still get a
    ``WorkerPreflightError`` on failure. These tests pin that contract; the
    real probe is exercised in tests/test_doctor.py.
    """

    def setUp(self) -> None:
        self.worker = importlib.import_module("gym_anything.remote.worker")

    def test_check_kvm_access_is_reexported(self) -> None:
        self.assertTrue(callable(getattr(self.worker, "check_kvm_access", None)))
        self.assertTrue(issubclass(self.worker.WorkerPreflightError, RuntimeError))

    def test_check_kvm_access_translates_doctor_failure(self) -> None:
        with mock.patch(
            "gym_anything.remote.worker._doctor_check_kvm_access",
            side_effect=RuntimeError("/dev/kvm does not exist"),
        ):
            with self.assertRaisesRegex(self.worker.WorkerPreflightError, "does not exist"):
                self.worker.check_kvm_access("/dev/kvm")

    def test_check_kvm_access_passes_through_on_success(self) -> None:
        with mock.patch(
            "gym_anything.remote.worker._doctor_check_kvm_access",
            return_value=None,
        ) as probe:
            self.worker.check_kvm_access("/dev/kvm")
        probe.assert_called_once_with("/dev/kvm")


class WorkerPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = importlib.import_module("gym_anything.remote.worker")

    def test_skip_returns_empty_list_without_probing(self) -> None:
        with mock.patch(
            "gym_anything.remote.worker.get_runner_status"
        ) as status_mock:
            result = self.worker.run_runner_preflight(skip=True)
        self.assertEqual(result, [])
        status_mock.assert_not_called()

    def test_returns_sorted_available_runners(self) -> None:
        fake_status = {
            "docker": {"available": True, "deps": {"docker": {"installed": True}}},
            "qemu": {"available": False, "deps": {"apptainer": {"installed": False}}},
            "local": {"available": True, "deps": {}},
        }
        with mock.patch(
            "gym_anything.remote.worker.get_runner_status", return_value=fake_status
        ):
            result = self.worker.run_runner_preflight()
        self.assertEqual(result, ["docker", "local"])

    def test_must_support_raises_when_runner_missing(self) -> None:
        fake_status = {
            "docker": {"available": True, "deps": {}},
            "qemu": {
                "available": False,
                "deps": {"apptainer": {"installed": False}, "kvm": {"installed": False}},
            },
            "local": {"available": True, "deps": {}},
        }
        with mock.patch(
            "gym_anything.remote.worker.get_runner_status", return_value=fake_status
        ):
            with self.assertRaisesRegex(
                self.worker.WorkerPreflightError, "must-support runners not satisfied"
            ):
                self.worker.run_runner_preflight(must_support=["qemu"])

    def test_must_support_passes_when_runner_available(self) -> None:
        fake_status = {
            "docker": {"available": True, "deps": {}},
            "local": {"available": True, "deps": {}},
        }
        with mock.patch(
            "gym_anything.remote.worker.get_runner_status", return_value=fake_status
        ):
            result = self.worker.run_runner_preflight(must_support=["docker"])
        self.assertIn("docker", result)

    def test_no_runners_available_raises(self) -> None:
        fake_status = {
            "docker": {"available": False, "deps": {}},
        }
        with mock.patch(
            "gym_anything.remote.worker.get_runner_status", return_value=fake_status
        ):
            with self.assertRaisesRegex(
                self.worker.WorkerPreflightError, "no runner is available"
            ):
                self.worker.run_runner_preflight()


if __name__ == "__main__":
    unittest.main()
