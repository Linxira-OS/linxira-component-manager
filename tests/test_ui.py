from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from linxira_component_manager.ui import MainWindow, NODE_ID, PlanDialog


EXAMPLE = Path(__file__).parents[1] / "examples" / "catalog-v3.example.json"


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_application_leaf_details_and_status_refresh(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["applications"] = [{
            "id": "qgis",
            "kind": "application",
            "name": "QGIS",
            "description": "Desktop geographic information system",
            "provider": "pacman",
            "source": "arch",
            "license": {"spdx": "GPL-2.0-or-later"},
            "availability": {"status": "available"},
        }]
        document["bundles"][0]["children"]["recommended"].append("qgis")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            window = MainWindow(path)
            qgis_item = next(item for item in window._iter_items() if item.data(0, NODE_ID) == "qgis")
            window._current_changed(qgis_item, None)
            window.selection.set_bundle("data-science", True)
            window._refresh()

            self.assertTrue(window.tree.topLevelItem(0).isExpanded())
            self.assertFalse(
                any(
                    window.tree.topLevelItem(index).isExpanded()
                    for index in range(1, window.tree.topLevelItemCount())
                )
            )
            self.assertEqual(qgis_item.text(2), "application")
            self.assertFalse(qgis_item.isDisabled())
            self.assertIn("Kind: application", window.details.toPlainText())
            self.assertIn("unique leaf item(s)", window.summary.text())
            window.close()

    def test_confirmation_dialog_shows_full_plan_pending_and_unsupported(self) -> None:
        plan = {
            "directPackageTargets": [],
            "pendingItems": ["conda-env"],
            "unsupportedItems": ["flatpak-tool"],
            "leafRequirements": [
                {"id": "conda-env", "status": "pending"},
                {"id": "flatpak-tool", "status": "unsupported"},
            ],
        }
        dialog = PlanDialog(plan)
        self.assertIn("conda-env", dialog.pending_label.text())
        self.assertIn("flatpak-tool", dialog.unsupported_label.text())
        self.assertEqual(json.loads(dialog.document.toPlainText()), plan)
        button_box = dialog.findChild(QDialogButtonBox)
        self.assertIsNotNone(button_box)
        self.assertEqual(
            button_box.button(QDialogButtonBox.StandardButton.Ok).text(),
            "Confirm and apply",
        )
        dialog.close()


if __name__ == "__main__":
    unittest.main()
