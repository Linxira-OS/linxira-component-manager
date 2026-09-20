from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .about import show_about
from .backend import (
    ApplyResult,
    Transaction,
    confirm_and_apply,
    discard_transaction,
    load_installer_deferred,
    load_inventory,
    plan_selection,
)
from .catalog import Bundle, Catalog, CatalogError, Leaf, load_catalog
from .selection import SelectionError, SelectionModel


NODE_ID = Qt.ItemDataRole.UserRole
NODE_PATH = Qt.ItemDataRole.UserRole + 1
NODE_KIND = Qt.ItemDataRole.UserRole + 2


class PlanThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, selection: dict[str, object], catalog_path: Path) -> None:
        super().__init__()
        self.selection = selection
        self.catalog_path = catalog_path

    def run(self) -> None:
        try:
            self.succeeded.emit(plan_selection(self.selection, self.catalog_path))
        except Exception as exc:
            self.failed.emit(str(exc))


class ApplyThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, transaction: Transaction) -> None:
        super().__init__()
        self.transaction = transaction

    def run(self) -> None:
        try:
            self.succeeded.emit(
                confirm_and_apply(self.transaction, progress=self.progress.emit)
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class PlanDialog(QDialog):
    def __init__(self, plan: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm component plan")
        self.resize(760, 620)
        layout = QVBoxLayout(self)

        targets = plan.get("directPackageTargets", [])
        pending = plan.get("pendingItems", [])
        unsupported = plan.get("unsupportedItems", [])
        heading = QLabel(f"Ready package targets: {len(targets)}")
        heading.setFont(QFont(heading.font().family(), 13, QFont.Weight.DemiBold))
        layout.addWidget(heading)
        self.pending_label = QLabel(
            "Pending items (not applied): " + (", ".join(pending) if pending else "None")
        )
        self.pending_label.setWordWrap(True)
        self.unsupported_label = QLabel(
            "Unsupported items (not applied): " + (", ".join(unsupported) if unsupported else "None")
        )
        self.unsupported_label.setWordWrap(True)
        layout.addWidget(self.pending_label)
        layout.addWidget(self.unsupported_label)
        if not targets:
            notice = QLabel(
                "This plan has no direct package targets. Confirmation will be recorded, "
                "but administrator authorization will not be requested."
            )
        else:
            notice = QLabel(
                "Review the complete immutable backend plan. Confirmation will request administrator authorization."
            )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        self.document = QPlainTextEdit(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        self.document.setReadOnly(True)
        self.document.setAccessibleName("Complete backend transaction plan")
        layout.addWidget(self.document, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Confirm and apply")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self, catalog_path: Path | None = None):
        super().__init__()
        self.catalog: Catalog | None = None
        self.selection: SelectionModel | None = None
        self.plan_worker: PlanThread | None = None
        self.apply_worker: ApplyThread | None = None
        self.installed_states: dict[str, str] = {}
        self.setWindowTitle("快速配置系统运行时")
        self.resize(1180, 760)
        self._build_ui()
        if catalog_path is not None:
            self.open_catalog(catalog_path)

    def _build_ui(self) -> None:
        open_action = QAction("Open Catalog...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_catalog)
        save_action = QAction("Save Selection...", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_selection)
        self.menuBar().addMenu("File").addActions([open_action, save_action])
        about_action = QAction("About Quick System Runtime Setup", self)
        about_action.triggered.connect(lambda: show_about(self))
        self.menuBar().addMenu("Help").addAction(about_action)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Bundle / component", "Role", "Policy"])
        self.tree.setColumnWidth(0, 430)
        self.tree.setAccessibleName("Expandable component selection tree")
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(self._current_changed)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Selected node details")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Selection JSON preview")
        fixed = QFont("monospace")
        fixed.setStyleHint(QFont.StyleHint.Monospace)
        self.preview.setFont(fixed)
        self.plan_preview = QPlainTextEdit()
        self.plan_preview.setReadOnly(True)
        self.plan_preview.setFont(fixed)

        tabs = QTabWidget()
        tabs.addTab(self.details, "Details")
        tabs.addTab(self.preview, "Selection JSON")
        tabs.addTab(self.plan_preview, "Backend plan")
        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(tabs)
        splitter.setSizes([650, 530])

        self.summary = QLabel("Open a Catalog v3 JSON file to begin.")
        self.summary.setWordWrap(True)
        save_button = QPushButton("Save selection JSON")
        save_button.clicked.connect(self.save_selection)
        self.plan_button = QPushButton("Plan with linxira-components")
        self.plan_button.clicked.connect(self.plan_backend)
        buttons = QHBoxLayout()
        buttons.addWidget(self.summary, 1)
        buttons.addWidget(save_button)
        buttons.addWidget(self.plan_button)
        layout = QVBoxLayout()
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedWidth(260)
        self.progress_bar.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress_bar)

    def choose_catalog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open Catalog v3", "", "JSON files (*.json)")
        if filename:
            self.open_catalog(Path(filename))

    def open_catalog(self, path: Path) -> None:
        try:
            catalog = load_catalog(path)
        except CatalogError as exc:
            QMessageBox.critical(self, "Invalid catalog", str(exc))
            return
        self.catalog = catalog
        self.selection = SelectionModel(catalog)
        try:
            self.installed_states = load_inventory(path)
        except Exception as exc:
            self.installed_states = {}
            self.statusBar().showMessage(f"Installed state unavailable: {exc}", 8000)
        self.tree.blockSignals(True)
        self.tree.clear()
        for bundle_id in catalog.top_level_bundle_ids:
            self._add_bundle(None, bundle_id, (bundle_id,), "")
        partial_paths: dict[str, tuple[str, ...]] = {}
        for item in self._iter_items():
            leaf_id = item.data(0, NODE_ID)
            if (
                item.data(0, NODE_KIND) == "leaf"
                and self.installed_states.get(leaf_id) == "partial"
                and leaf_id not in partial_paths
            ):
                partial_paths[leaf_id] = tuple(item.data(0, NODE_PATH))
        # 2026-09-20: 安装时因离线被延后的组件在此接手 —— 预选进当前选择,
        # 用户确认 plan 即可完成安装(此前这些组件会静默消失)。
        deferred_ids = (
            set(load_installer_deferred())
            & set(self.catalog.leaves)
            - {
                leaf_id
                for leaf_id, state in self.installed_states.items()
                if state == "installed"
            }
        )
        deferred_paths: dict[str, tuple[str, ...]] = {}
        if deferred_ids:
            for item in self._iter_items():
                leaf_id = item.data(0, NODE_ID)
                if (
                    item.data(0, NODE_KIND) == "leaf"
                    and leaf_id in deferred_ids
                    and leaf_id not in partial_paths
                    and leaf_id not in deferred_paths
                ):
                    deferred_paths[leaf_id] = tuple(item.data(0, NODE_PATH))
        self.selection.load_reconciled_paths(
            [*partial_paths.values(), *deferred_paths.values()]
        )
        self.tree.blockSignals(False)
        self.tree.collapseAll()
        if self.tree.topLevelItemCount():
            self.tree.topLevelItem(0).setExpanded(True)
        self.statusBar().showMessage(f"Loaded {path}")
        if deferred_paths:
            self.statusBar().showMessage(
                "Installer deferred {} component(s) at install time; they are pre-selected — "
                "plan to finish installing them.".format(len(deferred_paths)),
                15000,
            )
        self._refresh()

    def _add_bundle(
        self,
        parent: QTreeWidgetItem | None,
        bundle_id: str,
        path: tuple[str, ...],
        role: str,
    ) -> None:
        assert self.catalog is not None
        bundle = self.catalog.bundles[bundle_id]
        item = QTreeWidgetItem(parent or self.tree, [bundle.name, role, self._policy_text(bundle)])
        item.setData(0, NODE_ID, bundle_id)
        item.setData(0, NODE_PATH, list(path))
        item.setData(0, NODE_KIND, "bundle")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setToolTip(0, bundle.description)
        for child in bundle.children:
            child_path = path + (child.id,)
            if child.id in self.catalog.bundles:
                self._add_bundle(item, child.id, child_path, child.role)
            else:
                self._add_leaf(item, self.catalog.leaves[child.id], child_path, child.role)

    def _add_leaf(
        self,
        parent: QTreeWidgetItem,
        leaf: Leaf,
        path: tuple[str, ...],
        role: str,
    ) -> None:
        label = leaf.name
        if leaf.offline_label:
            label += f" · {leaf.offline_label}"
        item = QTreeWidgetItem(parent, [label, role, leaf.kind])
        item.setData(0, NODE_ID, leaf.id)
        item.setData(0, NODE_PATH, list(path))
        item.setData(0, NODE_KIND, "leaf")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setToolTip(0, leaf.description)
        if not leaf.available:
            item.setDisabled(True)
            item.setToolTip(0, leaf.unavailable_reason or "Unavailable")

    @staticmethod
    def _policy_text(bundle: Bundle) -> str:
        if bundle.policy == "bounded":
            return f"bounded (max {bundle.max_selected})"
        return bundle.policy

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self.selection is None:
            return
        node_id = item.data(0, NODE_ID)
        kind = item.data(0, NODE_KIND)
        checked = item.checkState(0) == Qt.CheckState.Checked
        try:
            if kind == "bundle":
                self.selection.set_bundle(node_id, checked)
            else:
                self.selection.set_leaf(node_id, checked, tuple(item.data(0, NODE_PATH)))
        except SelectionError as exc:
            QMessageBox.warning(self, "Selection blocked", str(exc))
        self._refresh()

    def _iter_items(self):
        stack = [self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(index) for index in range(item.childCount()))

    def _refresh(self) -> None:
        if self.selection is None or self.catalog is None:
            return
        selected = self.selection.selected_leaf_ids
        installed = {
            leaf_id for leaf_id, state in self.installed_states.items()
            if state == "installed"
        }
        effective = set(selected) | installed
        self.tree.blockSignals(True)
        for item in self._iter_items():
            node_id = item.data(0, NODE_ID)
            kind = item.data(0, NODE_KIND)
            if kind == "bundle":
                leaves = {
                    leaf_id for leaf_id in self.catalog.leaf_ids(node_id)
                    if self.catalog.leaves[leaf_id].available
                }
                count = len(leaves & effective)
                state = 0 if not count else 2 if count == len(leaves) else 1
                states = (Qt.CheckState.Unchecked, Qt.CheckState.PartiallyChecked, Qt.CheckState.Checked)
                item.setCheckState(0, states[state])
            else:
                installed_state = self.installed_states.get(node_id)
                if installed_state == "installed":
                    item.setCheckState(0, Qt.CheckState.Checked)
                elif installed_state == "partial":
                    item.setCheckState(0, Qt.CheckState.PartiallyChecked)
                else:
                    item.setCheckState(0, Qt.CheckState.Checked if node_id in selected else Qt.CheckState.Unchecked)
                leaf = self.catalog.leaves[node_id]
                required = self.selection.is_required(node_id)
                item.setDisabled(not leaf.available or required or installed_state == "installed")
                if required:
                    item.setToolTip(0, f"{leaf.description}\nRequired by an active bundle; cannot be cleared.")
                elif installed_state == "installed":
                    item.setToolTip(0, f"{leaf.description}\nInstalled package cohort; removal is not supported.")
                elif installed_state == "partial":
                    item.setToolTip(0, f"{leaf.description}\nPartially installed; apply will install the missing package targets.")
        self.tree.blockSignals(False)
        document = self.selection.document()
        self.preview.setPlainText(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
        invalid = sum(not result["valid"] for result in document["constraintResults"])
        self.summary.setText(
            f"{len(selected)} unique leaf item(s), {len(document['selectedBundleIds'])} active bundle(s), "
            f"{invalid} invalid constraint(s). Leaf IDs are de-duplicated globally."
        )

    def _current_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if current is None or self.catalog is None:
            self.details.clear()
            return
        node_id = current.data(0, NODE_ID)
        path = "/".join(current.data(0, NODE_PATH))
        if node_id in self.catalog.leaves:
            node = self.catalog.leaves[node_id]
            text = (
                f"{node.name}\n\n{node.description}\n\nStable ID: {node.id}\nKind: {node.kind}\n"
                f"Provider: {node.provider}\nSource: {node.source}\nLicense: {node.license}\n"
                f"Offline policy: {node.offline_label or node.offline_policy or '-'}\nPath: {path}"
            )
        else:
            node = self.catalog.bundles[node_id]
            text = (
                f"{node.name}\n\n{node.description}\n\nStable ID: {node.id}\n"
                f"Selection policy: {self._policy_text(node)}\nPath: {path}"
            )
        self.details.setPlainText(text)

    def save_selection(self) -> None:
        if self.selection is None:
            QMessageBox.information(self, "No catalog", "Open a catalog before saving a selection.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save selection", "selection.json", "JSON files (*.json)"
        )
        if not filename:
            return
        try:
            Path(filename).write_text(
                json.dumps(self.selection.document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.statusBar().showMessage(f"Saved {filename}", 5000)

    def plan_backend(self) -> None:
        if self.selection is None or self.catalog is None:
            QMessageBox.information(self, "No catalog", "Open a catalog before planning.")
            return
        if not self.selection.selected_leaf_ids:
            QMessageBox.information(self, "Empty selection", "Select at least one component before planning.")
            return
        self.plan_button.setEnabled(False)
        self.statusBar().showMessage("Creating backend plan...")
        self.plan_worker = PlanThread(self.selection.document(), self.catalog.path)
        self.plan_worker.succeeded.connect(self._plan_succeeded)
        self.plan_worker.failed.connect(self._plan_failed)
        self.plan_worker.finished.connect(self._plan_finished)
        self.plan_worker.start()

    def _plan_succeeded(self, transaction: Transaction) -> None:
        self.plan_preview.setPlainText(
            json.dumps(transaction.plan, ensure_ascii=False, indent=2, sort_keys=True)
        )
        dialog = PlanDialog(transaction.plan, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            discard_transaction(transaction)
            self.statusBar().showMessage("Plan cancelled; no changes were applied.", 5000)
            return
        self.plan_button.setEnabled(False)
        self.statusBar().showMessage("Confirming and applying the transaction...")
        self.progress_bar.setVisible(True)
        self.apply_worker = ApplyThread(transaction)
        self.apply_worker.succeeded.connect(self._apply_succeeded)
        self.apply_worker.failed.connect(self._apply_failed)
        self.apply_worker.finished.connect(self._apply_finished)
        self.apply_worker.progress.connect(self._apply_progress)
        self.apply_worker.start()

    def _apply_progress(self, stage: str) -> None:
        self.statusBar().showMessage(stage)

    def _plan_failed(self, message: str) -> None:
        self.plan_preview.setPlainText(f"FAIL-CLOSED\n\n{message}")
        QMessageBox.warning(self, "Backend planning unavailable", message)

    def _plan_finished(self) -> None:
        if self.plan_worker is not None:
            self.plan_worker.deleteLater()
        self.plan_worker = None
        if self.apply_worker is None:
            self.plan_button.setEnabled(True)
            self.statusBar().clearMessage()

    def _apply_succeeded(self, result: ApplyResult) -> None:
        if self.catalog is not None:
            self.open_catalog(self.catalog.path)
        if result.applied:
            message = result.output or "The selected package targets were applied successfully."
            QMessageBox.information(self, "Components applied", message)
        else:
            QMessageBox.information(self, "Plan confirmed", result.output)

    def _apply_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Component transaction failed", message)

    def _apply_finished(self) -> None:
        if self.apply_worker is not None:
            self.apply_worker.deleteLater()
        self.apply_worker = None
        self.progress_bar.setVisible(False)
        self.plan_button.setEnabled(True)
        self.statusBar().clearMessage()
