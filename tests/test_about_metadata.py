from pathlib import Path
import tomllib
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).parents[1]
REPOSITORY = "https://github.com/Linxira-OS/linxira-component-manager"


class AboutMetadataTests(unittest.TestCase):
    def test_about_and_metadata_urls_match(self):
        about = (ROOT / "src/linxira_component_manager/about.py").read_text(encoding="utf-8")
        ui = (ROOT / "src/linxira_component_manager/ui.py").read_text(encoding="utf-8")
        for text in ("Linxira OS contributors", "MIT License", REPOSITORY, "DOCUMENTATION_URL"):
            self.assertIn(text, about)
        self.assertIn('addMenu("Help")', ui)
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["urls"]["Repository"], REPOSITORY)
        component = ET.parse(ROOT / "data/org.linxira.ComponentManager.metainfo.xml").getroot()
        urls = {node.attrib["type"]: node.text for node in component.findall("url")}
        self.assertEqual(set(urls), {"homepage", "vcs-browser", "bugtracker", "help"})
        self.assertEqual(urls["bugtracker"], REPOSITORY + "/issues")
