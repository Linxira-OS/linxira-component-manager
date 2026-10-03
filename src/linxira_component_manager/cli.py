"""linxira-component-manager 的指令模式：人写命令、agent 调命令，同一语义。

与 GUI/TUI 共用同一事务核（backend.plan_selection / confirm_and_apply）——
指令、TUI、GUI、AI agent 四条入口走的是同一条 plan → confirm → apply 链。

退出码：0 成功；2 选择/计划被拒；3 授权或执行失败；64 用法错误。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .backend import (
    BackendError,
    confirm_and_apply,
    discard_transaction,
    load_inventory,
    plan_selection,
)
from .catalog import Catalog, CatalogError, load_catalog
from .selection import SelectionError, SelectionModel

DEFAULT_CATALOGS = (
    Path("/usr/share/linxira/catalog/catalog-v3.json"),
    Path("/usr/share/linxira/catalog/catalog.json"),
)

EXIT_PLAN = 2
EXIT_APPLY = 3

INSTALLER_KINDS = ("component", "application")


def default_catalog() -> Path | None:
    return next((path for path in DEFAULT_CATALOGS if path.is_file()), None)


def resolve_catalog(argument: Path | None) -> Path:
    path = argument or default_catalog()
    if path is None or not path.is_file():
        raise CatalogError(
            "catalog not found: install linxira-catalog or pass --catalog PATH"
        )
    return path


def _leaf_rows(catalog: Catalog, *, states: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for leaf in sorted(catalog.leaves.values(), key=lambda item: item.id):
        if leaf.kind not in INSTALLER_KINDS or not leaf.available:
            continue
        rows.append({
            "id": leaf.id,
            "name": leaf.name,
            "kind": leaf.kind,
            "provider": leaf.provider,
            "offlinePolicy": leaf.offline_policy,
            "state": states.get(leaf.id, "unknown"),
        })
    return rows


def _emit(rows: list[dict[str, object]] | dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(rows, dict):
        rows = [rows]
    for row in rows:
        state = row.get("state", "")
        print(f"{row['id']:34} {str(row['name'])[:24]:24} {str(row.get('provider', '')):8} {state}")



def bundle_path(catalog: Catalog, leaf_id: str) -> tuple[str, ...]:
    """事务引擎校验 requestedBy 的完整嵌套链(bundle/…/leaf), 且首段必须是
    bundle; 中段必须逐层是直接父子关系。这里 DFS 出一条真实链。"""
    def walk(node_id: str, chain: tuple[str, ...]) -> tuple[str, ...] | None:
        if node_id == leaf_id:
            return chain
        bundle = catalog.bundles.get(node_id)
        if bundle is None:
            return None
        for child in bundle.children:
            found = walk(child.id, chain + (child.id,))
            if found is not None:
                return found
        return None

    for bundle_id in sorted(catalog.bundles):
        found = walk(bundle_id, (bundle_id,))
        if found is not None:
            return found
    raise SelectionError(f"{leaf_id} is not part of any installable bundle")


def command_list(catalog_path: Path, *, as_json: bool) -> int:
    path = resolve_catalog(catalog_path)
    catalog = load_catalog(path)
    try:
        states = load_inventory(path)
    except BackendError:
        states = {}
    _emit(_leaf_rows(catalog, states=states), as_json)
    return 0


def command_status(catalog_path: Path, ids: list[str], *, as_json: bool) -> int:
    path = resolve_catalog(catalog_path)
    catalog = load_catalog(path)
    try:
        states = load_inventory(path)
    except BackendError:
        states = {}
    unknown = [leaf_id for leaf_id in ids if leaf_id not in catalog.leaves]
    if unknown:
        print(f"unknown leaf id(s): {', '.join(unknown)}", file=sys.stderr)
        return EXIT_PLAN
    rows = [
        {
            "id": leaf_id,
            "name": catalog.leaves[leaf_id].name,
            "state": states.get(leaf_id, "unknown"),
        }
        for leaf_id in ids
    ]
    _emit(rows, as_json)
    return 0


def command_install(
    catalog_path: Path,
    ids: list[str],
    *,
    assume_yes: bool,
    as_json: bool,
    dry_run: bool,
    authorization: str = "auto",
) -> int:
    path = resolve_catalog(catalog_path)
    catalog = load_catalog(path)
    model = SelectionModel(catalog)
    try:
        for leaf_id in ids:
            model.set_leaf(leaf_id, True, bundle_path(catalog, leaf_id))
        transaction = plan_selection(model.document(), path)
    except (SelectionError, CatalogError, BackendError) as error:
        print(f"无法生成安装计划: {error}", file=sys.stderr)
        return EXIT_PLAN

    targets = transaction.plan.get("directPackageTargets", [])

    if dry_run:
        discard_transaction(transaction)
        payload = {"dryRun": True, "directPackageTargets": targets}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if as_json else
              "\n".join(f"plan: {item}" for item in targets))
        return 0

    pending_items = transaction.plan.get("pendingItems", [])
    if not assume_yes:
        print(f"将安装 {len(targets)} 个包目标: {' '.join(targets)}")
        if pending_items:
            print(f"另有 {len(pending_items)} 项暂不可安装（通道待实现，将跳过）: {' '.join(pending_items)}")
        try:
            reply = input("继续? [y/N] ")
        except EOFError:
            reply = ""
        if reply.strip().lower() not in {"y", "yes"}:
            discard_transaction(transaction)
            print("已取消。", file=sys.stderr)
            return EXIT_PLAN

    try:
        confirm_and_apply(transaction, authorization=authorization)
    except BackendError as error:
        print(f"执行失败: {error}", file=sys.stderr)
        return EXIT_APPLY
    pending_items = transaction.plan.get("pendingItems", [])
    if as_json:
        print(json.dumps({"applied": True, "targets": targets, "pending": pending_items},
                         ensure_ascii=False))
    else:
        done = f"已安装 {len(targets)} 个包目标。"
        if pending_items:
            done += f" 另有 {len(pending_items)} 项通道待实现，本轮跳过: {' '.join(pending_items)}。"
        print(done)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linxira-component-manager",
        description="Linxira 组件安装器 —— 指令模式(与 GUI 同一条事务链)",
    )
    parser.add_argument("--catalog", type=Path, default=None, help="catalog v3 JSON 路径")
    commands = parser.add_subparsers(dest="command")

    listing = commands.add_parser("list", help="列出可安装项")
    listing.add_argument("--json", action="store_true", help="机器可读输出")

    status = commands.add_parser("status", help="查询安装状态")
    status.add_argument("ids", nargs="+")
    status.add_argument("--json", action="store_true")

    install = commands.add_parser("install", help="安装组件/应用(经 plan→confirm→apply)")
    install.add_argument("ids", nargs="+")
    install.add_argument("--yes", action="store_true", help="跳过交互确认(agent 场景)")
    install.add_argument("--json", action="store_true")
    install.add_argument("--dry-run", action="store_true", help="只输出计划不执行")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "list":
            return command_list(arguments.catalog, as_json=arguments.json)
        if arguments.command == "status":
            return command_status(arguments.catalog, arguments.ids, as_json=arguments.json)
        if arguments.command == "install":
            return command_install(
                arguments.catalog,
                arguments.ids,
                assume_yes=arguments.yes,
                as_json=arguments.json,
                dry_run=arguments.dry_run,
            )
    except (CatalogError, BackendError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_PLAN
    parser.print_help()
    return 64
