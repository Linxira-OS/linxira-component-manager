from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget


APP_NAME = "Quick System Runtime Setup"
APP_VERSION = "0.1.0"
HOMEPAGE_URL = "https://linxira-os.github.io/"
REPOSITORY_URL = "https://github.com/Linxira-OS/linxira-component-manager"
ISSUES_URL = f"{REPOSITORY_URL}/issues"
DOCUMENTATION_URL = "https://linxira-os.github.io/linxira-wiki/"


def show_about(parent: QWidget | None = None) -> QDialog:
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"About {APP_NAME}")
    dialog.setMinimumWidth(420)
    layout = QVBoxLayout(dialog)
    title = QLabel(f"<h2>{APP_NAME}</h2><p>Version {APP_VERSION}</p>")
    title.setTextFormat(Qt.TextFormat.RichText)
    layout.addWidget(title)
    details = QLabel(
        "<p>Developed by Linxira OS contributors.<br>Licensed under the MIT License.</p>"
        f'<p><a href="{HOMEPAGE_URL}">Linxira OS homepage</a><br>'
        f'<a href="{REPOSITORY_URL}">Project repository</a><br>'
        f'<a href="{ISSUES_URL}">Report an issue</a><br>'
        f'<a href="{DOCUMENTATION_URL}">Documentation</a></p>'
    )
    details.setOpenExternalLinks(True)
    details.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    layout.addWidget(details)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.open()
    return dialog
