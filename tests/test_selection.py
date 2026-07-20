from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from linxira_component_manager.catalog import load_catalog
from linxira_component_manager.selection import SelectionError, SelectionModel


EXAMPLE = Path(__file__).parents[1] / "examples" / "catalog-v3.example.json"


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(EXAMPLE)
        self.selection = SelectionModel(self.catalog)

    def test_nested_preset_required_recommended_and_requested_by(self) -> None:
        self.selection.set_bundle("data-science", True)
        self.assertEqual(
            self.selection.selected_leaf_ids,
            frozenset({"python-runtime", "numpy-scipy", "jupyterlab"}),
        )
        document = self.selection.document()
        runtime = next(leaf for leaf in document["leaves"] if leaf["id"] == "python-runtime")
        self.assertEqual(
            runtime["requestedBy"],
            ["data-science/python-scientific-stack/python-runtime"],
        )
        self.assertIn("required", runtime["provenance"])

    def test_required_leaf_is_locked(self) -> None:
        self.selection.set_bundle("data-science", True)
        with self.assertRaisesRegex(SelectionError, "required"):
            self.selection.set_leaf(
                "python-runtime", False,
                ("data-science", "python-scientific-stack", "python-runtime"),
            )

    def test_optional_override_and_stable_leaf_deduplication(self) -> None:
        self.selection.set_bundle("data-science", True)
        path = ("data-science", "python-scientific-stack", "pyarrow")
        self.selection.set_leaf("pyarrow", True, path)
        self.selection.explicit_paths["pyarrow"].add(("another-view", "pyarrow"))
        document = self.selection.document()
        self.assertEqual(document["selectedLeafIds"].count("pyarrow"), 1)
        leaf = next(item for item in document["leaves"] if item["id"] == "pyarrow")
        self.assertEqual(len(leaf["requestedBy"]), 2)

    def test_application_leaf_keeps_stable_deduplication_across_nested_paths(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["applications"] = [{
            "id": "qgis",
            "kind": "application",
            "name": "QGIS",
            "provider": "pacman",
            "source": "arch",
            "availability": {"status": "available"},
        }]
        document["bundles"][0]["children"]["optional"].append("qgis")
        document["bundles"][2]["children"]["optional"].append("qgis")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            selection = SelectionModel(load_catalog(path))
            nested = ("data-science", "python-scientific-stack", "qgis")
            direct = ("data-science", "qgis")
            selection.set_leaf("qgis", True, nested)
            selection.set_leaf("qgis", True, direct)
            result = selection.document()

        self.assertEqual(result["selectedLeafIds"], ["qgis"])
        leaf = result["leaves"][0]
        self.assertEqual(
            leaf["requestedBy"],
            ["data-science/python-scientific-stack/qgis", "data-science/qgis"],
        )

    def test_exclusive_selection_clears_sibling(self) -> None:
        cpu_path = ("data-science", "ml-runtime-choice", "cpu-ml-runtime")
        gpu_path = ("data-science", "ml-runtime-choice", "gpu-ml-runtime")
        self.selection.set_leaf("cpu-ml-runtime", True, cpu_path)
        with self.assertRaisesRegex(SelectionError, "hardware policy"):
            self.selection.set_leaf("gpu-ml-runtime", True, gpu_path)
        self.assertIn("cpu-ml-runtime", self.selection.selected_leaf_ids)

    def test_parent_states_are_derived_from_effective_leaves(self) -> None:
        self.selection.set_bundle("data-science", True)
        self.assertEqual(self.selection.node_state("data-science"), 1)
        self.assertEqual(self.selection.node_state("python-runtime"), 2)

    def test_bounded_policy_rejects_excess_without_partial_mutation(self) -> None:
        self.catalog.bundles["ml-runtime-choice"] = replace(
            self.catalog.bundles["ml-runtime-choice"], policy="bounded", max_selected=1
        )
        cpu_path = ("data-science", "ml-runtime-choice", "cpu-ml-runtime")
        self.selection.set_leaf("cpu-ml-runtime", True, cpu_path)
        self.catalog.leaves["gpu-ml-runtime"] = replace(
            self.catalog.leaves["gpu-ml-runtime"], available=True, unavailable_reason=""
        )
        gpu_path = ("data-science", "ml-runtime-choice", "gpu-ml-runtime")
        with self.assertRaisesRegex(SelectionError, "at most 1"):
            self.selection.set_leaf("gpu-ml-runtime", True, gpu_path)
        self.assertEqual(self.selection.selected_leaf_ids, frozenset({"cpu-ml-runtime"}))


if __name__ == "__main__":
    unittest.main()
