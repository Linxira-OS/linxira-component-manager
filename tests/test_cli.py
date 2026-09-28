from __future__ import annotations

import json
from pathlib import Path
import tempfile
from unittest import mock
import unittest

from linxira_component_manager import cli
from linxira_component_manager.backend import Transaction
from linxira_component_manager.catalog import load_catalog

EXAMPLE = Path(__file__).parents[1] / "examples" / "catalog-v3.example.json"


def _transaction(plan: dict) -> Transaction:
    return Transaction(Path("/tmp/txn"), plan, Path("/tmp/catalog.json"), "/usr/bin/linxira-components")


class ListCommandTests(unittest.TestCase):
    def test_list_json_reports_available_installer_leaves(self) -> None:
        with mock.patch.object(cli, "load_inventory", return_value={}):
            with mock.patch("sys.stdout"):
                code = cli.command_list(EXAMPLE, as_json=True)
        self.assertEqual(code, 0)

    def test_list_skips_unavailable_and_desktop_leaves(self) -> None:
        catalog = load_catalog(EXAMPLE)
        with mock.patch.object(cli, "load_inventory", return_value={}):
            rows = cli._leaf_rows(catalog, states={})
        self.assertTrue(rows)
        self.assertTrue(all(row["kind"] in cli.INSTALLER_KINDS for row in rows))
        self.assertTrue(all(row["state"] == "unknown" for row in rows))


class StatusCommandTests(unittest.TestCase):
    def test_unknown_id_is_rejected(self) -> None:
        with mock.patch.object(cli, "load_inventory", return_value={}):
            code = cli.command_status(EXAMPLE, ["no-such-leaf"], as_json=False)
        self.assertEqual(code, cli.EXIT_PLAN)

    def test_known_id_reports_state(self) -> None:
        catalog = load_catalog(EXAMPLE)
        first = next(iter(catalog.leaves))
        with mock.patch.object(cli, "load_inventory", return_value={first: "installed"}):
            code = cli.command_status(EXAMPLE, [first], as_json=False)
        self.assertEqual(code, 0)


class InstallCommandTests(unittest.TestCase):
    def _first_available(self) -> str:
        catalog = load_catalog(EXAMPLE)
        return next(
            leaf.id for leaf in sorted(catalog.leaves.values(), key=lambda item: item.id)
            if leaf.kind in cli.INSTALLER_KINDS and leaf.available
        )

    def test_dry_run_plans_without_applying(self) -> None:
        leaf_id = self._first_available()
        transaction = _transaction({
            "directPackageTargets": ["pkg-a"],
            "pendingItems": [],
            "unsupportedItems": [],
            "leafRequirements": [],
        })
        with mock.patch.object(cli, "plan_selection", return_value=transaction), \
             mock.patch.object(cli, "discard_transaction") as discard, \
             mock.patch.object(cli, "confirm_and_apply") as apply, \
             mock.patch("sys.stdout"):
            code = cli.command_install(
                EXAMPLE, [leaf_id], assume_yes=True, as_json=True, dry_run=True
            )
        self.assertEqual(code, 0)
        apply.assert_not_called()
        discard.assert_called_once_with(transaction)

    def test_install_runs_confirm_and_apply_with_yes(self) -> None:
        leaf_id = self._first_available()
        transaction = _transaction({
            "directPackageTargets": ["pkg-a"],
            "pendingItems": [],
            "unsupportedItems": [],
            "leafRequirements": [],
        })
        with mock.patch.object(cli, "plan_selection", return_value=transaction), \
             mock.patch.object(cli, "confirm_and_apply") as confirm, \
             mock.patch("sys.stdout"):
            code = cli.command_install(
                EXAMPLE, [leaf_id], assume_yes=True, as_json=False, dry_run=False
            )
        self.assertEqual(code, 0)
        confirm.assert_called_once()

    def test_apply_failure_maps_to_apply_exit_code(self) -> None:
        from linxira_component_manager.backend import BackendError

        leaf_id = self._first_available()
        transaction = _transaction({
            "directPackageTargets": ["pkg-a"],
            "pendingItems": [],
            "unsupportedItems": [],
            "leafRequirements": [],
        })
        with mock.patch.object(cli, "plan_selection", return_value=transaction), \
             mock.patch.object(cli, "confirm_and_apply", side_effect=BackendError("boom")), \
             mock.patch("sys.stderr"):
            code = cli.command_install(
                EXAMPLE, [leaf_id], assume_yes=True, as_json=False, dry_run=False
            )
        self.assertEqual(code, cli.EXIT_APPLY)

    def test_unavailable_leaf_is_rejected_as_plan_error(self) -> None:
        catalog = load_catalog(EXAMPLE)
        unavailable = [
            leaf.id for leaf in catalog.leaves.values() if not leaf.available
        ]
        if not unavailable:
            self.skipTest("example catalog has no unavailable leaf")
        with mock.patch("sys.stderr"):
            code = cli.command_install(
                EXAMPLE, unavailable[:1], assume_yes=True, as_json=False, dry_run=True
            )
        self.assertEqual(code, cli.EXIT_PLAN)
