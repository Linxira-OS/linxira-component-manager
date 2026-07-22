from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from linxira_component_manager.catalog import CatalogError, load_catalog


EXAMPLE = Path(__file__).parents[1] / "examples" / "catalog-v3.example.json"
CANONICAL = Path(os.environ.get(
    "LINXIRA_CATALOG_PATH", "/usr/share/linxira/catalog/catalog-v3.json"
))


class CatalogTests(unittest.TestCase):
    def test_loads_nested_catalog_and_finds_roots(self) -> None:
        catalog = load_catalog(EXAMPLE)
        self.assertEqual(catalog.top_level_bundle_ids, ("data-science",))
        self.assertTrue(all(bundle.surface == "components" for bundle in catalog.bundles.values()))
        self.assertEqual(
            catalog.leaf_ids("data-science"),
            frozenset({"python-runtime", "numpy-scipy", "pyarrow", "jupyterlab", "cpu-ml-runtime", "gpu-ml-runtime"}),
        )

    def test_loads_application_leaf_referenced_by_nested_bundle(self) -> None:
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
        document["bundles"][0]["children"]["optional"].append("qgis")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            catalog = load_catalog(path)

        self.assertEqual(catalog.leaves["qgis"].kind, "application")
        self.assertEqual(catalog.leaves["qgis"].license, "GPL-2.0-or-later")
        self.assertIn("qgis", catalog.leaf_ids("data-science"))

    def test_only_component_surface_roots_are_exposed_without_filtering_nested_bundles(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["applications"] = [{
            "id": "qgis",
            "kind": "application",
            "name": "QGIS",
            "provider": "pacman",
            "source": "arch",
        }]
        document["bundles"].extend([
            {
                "id": "application-tools",
                "surface": "applications",
                "name": "Application tools",
                "selection": "multi",
                "children": {"required": [], "recommended": ["qgis"], "optional": []},
            },
            {
                "id": "app-office",
                "surface": "applications",
                "name": "Office",
                "selection": "multi",
                "children": {"required": [], "recommended": ["qgis"], "optional": []},
            },
        ])
        document["bundles"][2]["children"]["optional"].append("application-tools")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            catalog = load_catalog(path)

        self.assertEqual(catalog.top_level_bundle_ids, ("data-science",))
        self.assertEqual(catalog.bundles["application-tools"].surface, "applications")
        self.assertIn("qgis", catalog.leaf_ids("data-science"))

    def test_accepts_desktop_surface_without_exposing_it_as_a_root(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["desktops"] = [{
            "id": "desktop-plasma",
            "kind": "desktop",
            "name": "Plasma",
            "provider": "pacman",
            "source": "arch",
        }]
        document["bundles"].append({
            "id": "desktop-environments",
            "surface": "desktops",
            "name": "Desktop environments",
            "selection": "exclusive",
            "children": {"required": ["desktop-plasma"], "recommended": [], "optional": []},
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            catalog = load_catalog(path)

        self.assertEqual(catalog.leaves["desktop-plasma"].kind, "desktop")
        self.assertNotIn("desktop-environments", catalog.top_level_bundle_ids)

    @unittest.skipUnless(CANONICAL.is_file(), "installed canonical Catalog v3 is unavailable")
    def test_canonical_catalog_does_not_expose_application_roots(self) -> None:
        catalog = load_catalog(CANONICAL)

        self.assertNotIn("app-web", catalog.top_level_bundle_ids)
        self.assertNotIn("app-office", catalog.top_level_bundle_ids)
        self.assertTrue(all(
            catalog.bundles[bundle_id].surface == "components"
            for bundle_id in catalog.top_level_bundle_ids
        ))

    def test_rejects_invalid_bundle_surface(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["bundles"][0]["surface"] = "system"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, r"invalid bundles\[0\]\.surface"):
                load_catalog(path)

    def test_rejects_kind_that_does_not_match_leaf_collection(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["components"][0]["kind"] = "application"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, r"invalid components\[0\]\.kind"):
                load_catalog(path)

    def test_rejects_cycle(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["bundles"][0]["children"]["optional"].append("data-science")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "cycle detected"):
                load_catalog(path)

    def test_rejects_duplicate_stable_id(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["components"].append(dict(document["components"][0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "duplicate stable ID"):
                load_catalog(path)

    def test_rejects_duplicate_stable_id_across_leaf_collections(self) -> None:
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        application = dict(document["components"][0])
        application["kind"] = "application"
        document["applications"] = [application]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "duplicate stable ID"):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
