"""linxira-component-manager 的终端 UI（curses，零额外依赖）。

与 GUI/CLI 共用同一事务核（backend.plan_selection / confirm_and_apply）。
键盘：↑/↓ 移动，空格 切换选择，a 全选/全不选，Enter 出计划并确认安装，
q 退出。授权模式 auto：root 直接执行，非 root 走 pkexec（同 GUI）。
"""
from __future__ import annotations

import curses
from pathlib import Path

from .backend import BackendError, confirm_and_apply, load_inventory, plan_selection
from .cli import DEFAULT_CATALOGS, bundle_path, resolve_catalog
from .selection import SelectionError, SelectionModel


def _installer_rows(catalog_path: Path) -> list[dict[str, object]]:
    from .catalog import load_catalog

    catalog = load_catalog(catalog_path)
    try:
        states = load_inventory(catalog_path)
    except BackendError:
        states = {}
    rows = []
    for leaf in sorted(catalog.leaves.values(), key=lambda item: item.id):
        if leaf.kind not in ("component", "application") or not leaf.available:
            continue
        rows.append({
            "id": leaf.id,
            "name": leaf.name,
            "provider": leaf.provider,
            "state": states.get(leaf.id, "unknown"),
        })
    return rows


def _draw(screen, rows: list[dict[str, object]], model, cursor: int, status: str) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    screen.addstr(0, 0, "Linxira 组件安装 (TUI)  —  空格:选择  Enter:安装  a:全选  q:退出", curses.A_REVERSE)
    selected = model.selected_leaf_ids
    for index, row in enumerate(rows):
        if index + 2 >= height - 2:
            break
        mark = "[x]" if row["id"] in selected else "[ ]"
        state = str(row["state"])[:10]
        line = f" {mark} {row['id']:<34} {str(row['name'])[:20]:<20} {state}"
        attributes = curses.A_REVERSE if index == cursor else curses.A_NORMAL
        try:
            screen.addstr(index + 2, 0, line[: width - 1], attributes)
        except curses.error:
            pass
    screen.addstr(height - 2, 0, status[: width - 1])
    screen.refresh()


def _apply(catalog_path: Path, model: SelectionModel) -> str:
    transaction = plan_selection(model.document(), catalog_path)
    targets = transaction.plan.get("directPackageTargets", [])
    result = confirm_and_apply(transaction, authorization="auto")
    return f"已提交 {len(targets)} 个包目标: {' '.join(targets)} → {result.message.splitlines()[0]}"

def run(catalog_argument: Path | None) -> int:
    catalog_path = resolve_catalog(catalog_argument)
    rows = _installer_rows(catalog_path)
    from .catalog import load_catalog

    model = SelectionModel(load_catalog(catalog_path))
    cursor = 0
    status = f"{len(rows)} 个可安装项"

    def inner(screen) -> int:
        nonlocal cursor, status
        while True:
            _draw(screen, rows, model, cursor, status)
            key = screen.getch()
            if key in (ord("q"), 27):
                return 0
            if key in (curses.KEY_UP, ord("k")) and rows:
                cursor = (cursor - 1) % len(rows)
            elif key in (curses.KEY_DOWN, ord("j")) and rows:
                cursor = (cursor + 1) % len(rows)
            elif key == ord(" "):
                leaf_id = str(rows[cursor]["id"])
                self_path = bundle_path(model.catalog, leaf_id)
                try:
                    model.set_leaf(leaf_id, leaf_id not in model.selected_leaf_ids, self_path)
                    status = f"选择 {len(model.selected_leaf_ids)} 项"
                except SelectionError as error:
                    status = str(error)
            elif key == ord("a"):
                want_all = len(model.selected_leaf_ids) != len(rows)
                for row in rows:
                    row_id = str(row["id"])
                    try:
                        model.set_leaf(row_id, want_all, bundle_path(model.catalog, row_id))
                    except SelectionError:
                        pass
                status = f"选择 {len(model.selected_leaf_ids)} 项"
            elif key in (curses.KEY_ENTER, 10, 13):
                if not model.selected_leaf_ids:
                    status = "未选择任何项"
                    continue
                try:
                    status = _apply(catalog_path, model)
                except (BackendError, SelectionError) as error:
                    status = f"失败: {error}"

    return curses.wrapper(inner)
