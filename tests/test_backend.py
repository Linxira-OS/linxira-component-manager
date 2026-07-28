from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from unittest import mock
import unittest

from linxira_component_manager.backend import (
    BackendError,
    _run,
    confirm_and_apply,
    discard_transaction,
    load_inventory,
    plan_selection,
)


def request_plan(*, targets: list[str] | None = None) -> dict[str, object]:
    package_targets = ["python"] if targets is None else targets
    pending = [] if package_targets else ["conda-env"]
    return {
        "schemaVersion": "org.linxira.components.request-plan.v2",
        "directPackageTargets": package_targets,
        "pendingItems": pending,
        "unsupportedItems": [],
        "leafRequirements": [{
            "id": "python-runtime" if package_targets else "conda-env",
            "status": "ready" if package_targets else "pending",
        }],
    }


class BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.catalog = Path(self.temporary.name) / "catalog.json"
        self.catalog.write_text("{}", encoding="utf-8")
        self.selection = {"selectedLeafIds": ["python-runtime"]}

    @mock.patch("linxira_component_manager.backend.subprocess.run")
    @mock.patch(
        "linxira_component_manager.backend.shutil.which",
        return_value="/usr/bin/linxira-components",
    )
    def test_plan_uses_selection_fixed_argv_and_keeps_transaction(self, _which, run) -> None:
        def fake_run(command, **kwargs):
            output_dir = Path(command[command.index("--output-dir") + 1])
            (output_dir / "request-plan.json").write_text(
                json.dumps(request_plan()), encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, "ok", "")

        run.side_effect = fake_run
        transaction = plan_selection(self.selection, self.catalog)
        self.addCleanup(discard_transaction, transaction)

        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["/usr/bin/linxira-components", "plan"])
        self.assertIn("--selection", command)
        self.assertNotIn("--component", command)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertTrue((transaction.directory / "selection.json").is_file())
        self.assertEqual(transaction.plan["directPackageTargets"], ["python"])

    @mock.patch("linxira_component_manager.backend.subprocess.run")
    @mock.patch("linxira_component_manager.backend.shutil.which", return_value="/usr/bin/linxira-components")
    def test_inventory_loads_installed_and_partial_leaf_states(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps({
            "schemaVersion": "org.linxira.components.installed-state.v1",
            "leaves": {
                "python-runtime": {"state": "installed"},
                "science-stack": {"state": "partial"},
            },
        }), "")
        states = load_inventory(self.catalog)
        self.assertEqual(states, {"python-runtime": "installed", "science-stack": "partial"})
        self.assertEqual(run.call_args.args[0][1], "inventory")

    @mock.patch("linxira_component_manager.backend.subprocess.run")
    @mock.patch("linxira_component_manager.backend.shutil.which")
    def test_confirm_then_pkexec_apply_and_cleanup(self, which, run) -> None:
        which.side_effect = lambda value: f"/usr/bin/{value}"
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(command)
            output_dir = Path(command[command.index("--output-dir") + 1]) if "--output-dir" in command else None
            if command[1] == "plan":
                (output_dir / "request-plan.json").write_text(
                    json.dumps(request_plan()), encoding="utf-8"
                )
            elif command[1] == "confirm":
                (output_dir / "confirmation.json").write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "applied", "")

        run.side_effect = fake_run
        transaction = plan_selection(self.selection, self.catalog)
        directory = transaction.directory
        result = confirm_and_apply(transaction)

        self.assertTrue(result.applied)
        self.assertEqual(calls[1][1], "confirm")
        self.assertEqual(calls[2][:3], [
            "/usr/bin/pkexec", "/usr/bin/linxira-components", "apply",
        ])
        self.assertEqual(calls[2][3:], ["--confirmation", str(directory / "confirmation.json")])
        self.assertTrue(all(call.kwargs["shell"] is False for call in run.call_args_list))
        self.assertFalse(directory.exists())

    @mock.patch("linxira_component_manager.backend.subprocess.run")
    @mock.patch("linxira_component_manager.backend.shutil.which")
    def test_pending_only_plan_confirms_without_pkexec(self, which, run) -> None:
        which.side_effect = lambda value: f"/usr/bin/{value}"

        def fake_run(command, **kwargs):
            output_dir = Path(command[command.index("--output-dir") + 1])
            if command[1] == "plan":
                (output_dir / "request-plan.json").write_text(
                    json.dumps(request_plan(targets=[])), encoding="utf-8"
                )
            else:
                (output_dir / "confirmation.json").write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        run.side_effect = fake_run
        transaction = plan_selection(self.selection, self.catalog)
        result = confirm_and_apply(transaction)

        self.assertFalse(result.applied)
        self.assertIn("authorization was not requested", result.output)
        self.assertEqual(run.call_count, 2)
        self.assertNotIn("pkexec", " ".join(run.call_args.args[0]))
        self.assertEqual(which.call_args_list, [mock.call("linxira-components")])

    @mock.patch("linxira_component_manager.backend.subprocess.run")
    @mock.patch("linxira_component_manager.backend.shutil.which")
    def test_installed_ready_plan_uses_privileged_apply_for_drift_recheck(self, which, run) -> None:
        which.side_effect = lambda value: f"/usr/bin/{value}"

        def fake_run(command, **kwargs):
            output_dir = Path(command[command.index("--output-dir") + 1]) if "--output-dir" in command else None
            if command[1] == "plan":
                plan = request_plan(targets=[])
                plan["pendingItems"] = []
                plan["leafRequirements"] = [{
                    "id": "python-runtime", "status": "ready", "packageTargets": [],
                }]
                (output_dir / "request-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            elif command[1] == "confirm":
                (output_dir / "confirmation.json").write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "verified", "")

        run.side_effect = fake_run
        result = confirm_and_apply(plan_selection(self.selection, self.catalog))
        self.assertTrue(result.applied)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args.args[0][:3], [
            "/usr/bin/pkexec", "/usr/bin/linxira-components", "apply",
        ])

    @mock.patch("linxira_component_manager.backend.subprocess.run")
    @mock.patch(
        "linxira_component_manager.backend.shutil.which",
        return_value="/usr/bin/linxira-components",
    )
    def test_confirmation_failure_cleans_transaction(self, _which, run) -> None:
        def fake_run(command, **kwargs):
            if command[1] == "plan":
                output_dir = Path(command[command.index("--output-dir") + 1])
                (output_dir / "request-plan.json").write_text(
                    json.dumps(request_plan()), encoding="utf-8"
                )
                return subprocess.CompletedProcess(command, 0, "ok", "")
            return subprocess.CompletedProcess(command, 2, "", "catalog drift")

        run.side_effect = fake_run
        transaction = plan_selection(self.selection, self.catalog)
        directory = transaction.directory
        with self.assertRaisesRegex(BackendError, "catalog drift"):
            confirm_and_apply(transaction)
        self.assertFalse(directory.exists())

    @mock.patch("linxira_component_manager.backend.subprocess.run")
    def test_json_error_message_is_unwrapped(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            [],
            3,
            "",
            '{"error":"TRANSACTION_FAILED","message":"pacman transaction failed\\nstderr:\\nmirror unavailable"}',
        )
        with self.assertRaisesRegex(BackendError, "mirror unavailable"):
            _run(["linxira-components", "apply"])

    @mock.patch("linxira_component_manager.backend.subprocess.run")
    @mock.patch(
        "linxira_component_manager.backend.shutil.which",
        return_value="/usr/bin/linxira-components",
    )
    def test_invalid_plan_fails_closed_and_cleans_up(self, _which, run) -> None:
        def fake_run(command, **kwargs):
            output_dir = Path(command[command.index("--output-dir") + 1])
            (output_dir / "request-plan.json").write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        run.side_effect = fake_run
        with self.assertRaisesRegex(BackendError, "directPackageTargets"):
            plan_selection(self.selection, self.catalog)


if __name__ == "__main__":
    unittest.main()
