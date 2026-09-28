from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .cli import DEFAULT_CATALOGS, main as cli_main


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="linxira-component-manager",
        description="Linxira 组件安装器（Quick System Runtime Setup）",
    )
    parser.add_argument("--catalog", type=Path, default=None, help="Catalog v3 JSON file")
    parser.add_argument("--tui", action="store_true", help="终端 UI（curses）")
    commands = parser.add_subparsers(dest="command")
    listing = commands.add_parser("list", help="列出可安装项（agent 友好，--json）")
    listing.add_argument("--json", action="store_true")
    status = commands.add_parser("status", help="查询安装状态")
    status.add_argument("ids", nargs="+")
    status.add_argument("--json", action="store_true")
    install = commands.add_parser("install", help="安装组件/应用（plan→confirm→apply）")
    install.add_argument("ids", nargs="+")
    install.add_argument("--yes", action="store_true", help="跳过交互确认（agent 场景）")
    install.add_argument("--json", action="store_true")
    install.add_argument("--dry-run", action="store_true", help="只输出计划不执行")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)

    if args.tui:
        from .tui import run as run_tui
        return run_tui(args.catalog)

    if args.command is not None:
        return cli_main(argv)

    # 图形界面按需导入：CLI/TUI 路径不要求图形栈。
    import os

    from PySide6.QtWidgets import QApplication

    from .ui import MainWindow

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    application = QApplication(sys.argv[:1])
    application.setApplicationName("Quick System Runtime Setup")
    application.setOrganizationName("Linxira OS")
    catalog = args.catalog or next(
        (path for path in DEFAULT_CATALOGS if path.is_file()), None
    )
    window = MainWindow(catalog)
    window.show()
    return application.exec()
