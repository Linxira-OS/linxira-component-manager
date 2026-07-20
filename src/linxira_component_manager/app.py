from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

from .ui import MainWindow


DEFAULT_CATALOGS = (
    Path("/usr/share/linxira/catalog/catalog-v3.json"),
    Path("/usr/share/linxira/catalog/catalog.json"),
)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="linxira-component-manager")
    parser.add_argument("catalog", nargs="?", type=Path, help="Catalog v3 JSON file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    application = QApplication(sys.argv[:1])
    application.setApplicationName("Linxira Component Manager")
    application.setOrganizationName("Linxira OS")
    catalog = args.catalog or next((path for path in DEFAULT_CATALOGS if path.is_file()), None)
    window = MainWindow(catalog)
    window.show()
    return application.exec()
