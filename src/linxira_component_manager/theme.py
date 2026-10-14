"""Linxira 视觉基准（与 linxira-welcome / linxira-package-center 同源，三处同步改）。

2026-10-14: 本程序此前完全没有样式层 —— 全靠平台主题兜底，与 Welcome 的
Fusion + 自定义调色板不是一个视觉体系。这里把 Welcome 的基准搬进来：
品牌青 #20b8a6（高亮）/ 深青 #147f78（主按钮），圆角 8-10px，深色跟随桌面。

放在独立模块而不是内联进 ui.py：PKGBUILD 用 `python -m installer` 装整个 wheel，
新模块自动随包发布，不需要改打包面。
"""

from __future__ import annotations

import subprocess

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#20b8a6"
ACCENT_STRONG = "#147f78"
SUCCESS = "#3fbf7f"
WARNING = "#e0a33e"
APPLICATION_ICON = "preferences-system-software"

THEME_QSS = """
QMainWindow, QDialog, QWidget { font-size: 13px; }
QLabel#heroTitle { font-size: 22px; font-weight: 700; }
QLabel#dialogTitle { font-size: 17px; font-weight: 700; }
QLabel#heroSubtitle { color: palette(placeholder-text); }
QFrame#heroCard { background: palette(base); border: 1px solid palette(midlight); border-radius: 10px; }
QTreeWidget#componentTree { background: palette(base); border: 1px solid palette(midlight);
                            border-radius: 10px; padding: 6px; outline: 0; }
QTreeWidget#componentTree::item { height: 34px; padding: 4px 6px; border-radius: 6px; }
QTreeWidget#componentTree::item:hover { background: rgba(32, 184, 166, 12%); }
QTreeWidget#componentTree::item:selected { background: rgba(32, 184, 166, 22%); color: palette(text); }
QHeaderView::section { background: transparent; border: 0; border-bottom: 1px solid palette(midlight);
                       padding: 8px 6px; font-weight: 600; color: palette(placeholder-text); }
QTabWidget#cardTabs::pane { background: palette(base); border: 1px solid palette(midlight);
                            border-radius: 10px; top: -1px; }
QTabWidget#cardTabs QTabBar::tab { background: transparent; border: 0; padding: 8px 14px;
                                   margin-right: 4px; color: palette(placeholder-text); }
QTabWidget#cardTabs QTabBar::tab:hover { color: palette(text); }
QTabWidget#cardTabs QTabBar::tab:selected { color: palette(text); font-weight: 600;
                                            border-bottom: 2px solid #20b8a6; }
QPlainTextEdit#codeView, QPlainTextEdit#detailView { background: transparent; border: 0;
                                                     padding: 10px; }
QPlainTextEdit#codeView { font-family: monospace; color: palette(text); }
QLabel#pill { background: rgba(32, 184, 166, 14%); color: #147f78; border-radius: 999px;
              padding: 6px 14px; font-weight: 600; }
QLabel#badgePill { background: rgba(224, 163, 62, 16%); color: #a9761f; border-radius: 999px;
                   padding: 4px 12px; }
QLabel#emptyState { color: palette(placeholder-text); padding: 20px; }
QLabel#summaryLabel { color: palette(placeholder-text); }
QPushButton { min-height: 34px; padding: 6px 16px; border-radius: 8px;
              border: 1px solid palette(midlight); background: palette(button); }
QPushButton:hover { border-color: #20b8a6; }
QPushButton#primaryButton { background: #147f78; color: #ffffff; border: 1px solid #147f78;
                            font-weight: 600; padding: 8px 20px; }
QPushButton#primaryButton:hover { background: #106c66; }
QPushButton#primaryButton:disabled { background: palette(mid); color: palette(placeholder-text);
                                     border-color: palette(mid); }
QProgressBar { border: 0; border-radius: 6px; background: palette(midlight); max-height: 6px;
               min-height: 6px; text-align: center; color: transparent; }
QProgressBar::chunk { background: #20b8a6; border-radius: 6px; }
QMenuBar, QStatusBar { background: transparent; }
"""


def _system_prefers_dark() -> bool:
    """跟随桌面深色模式 —— 读 freedesktop color-scheme portal(1=深色)。

    与 linxira-welcome 同源: Qt 在 COSMIC 下没有平台主题插件, 读不到桌面主题, 只能查 portal。
    """
    try:
        result = subprocess.run(
            ["gdbus", "call", "--session",
             "--dest", "org.freedesktop.portal.Desktop",
             "--object-path", "/org/freedesktop/portal/desktop",
             "--method", "org.freedesktop.portal.Settings.ReadOne",
             "org.freedesktop.appearance", "color-scheme"],
            capture_output=True, text=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return "uint32 1" in result.stdout


def _apply_dark_palette(app: QApplication) -> None:
    """Fusion + 深色调色板(高亮用品牌青 #20b8a6)；与 welcome 同一套色值。"""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#2a2e32"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e6eaed"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1f2326"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2a2e32"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e6eaed"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2a2e32"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e6eaed"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1f2326"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e6eaed"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#20b8a6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#4fc3f7"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9aa6a8"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#6b7478"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#6b7478"))
    app.setPalette(palette)


def apply_theme(application: QApplication) -> None:
    """应用 Linxira 视觉基准（Fusion + 深色跟随 + 全局 QSS + 窗口图标）。"""
    application.setStyle("Fusion")
    if _system_prefers_dark():
        _apply_dark_palette(application)
    application.setStyleSheet(THEME_QSS)
    icon = QIcon.fromTheme(APPLICATION_ICON)
    if not icon.isNull():
        application.setWindowIcon(icon)
