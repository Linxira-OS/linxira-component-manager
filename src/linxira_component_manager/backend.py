from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class Transaction:
    directory: Path
    plan: dict[str, Any]
    catalog_path: Path
    executable: str


@dataclass(frozen=True)
class ApplyResult:
    output: str
    applied: bool


def _run(command: list[str], *, timeout: int | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackendError(f"cannot run {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        try:
            document = json.loads(detail)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(document, dict) and isinstance(document.get("message"), str):
                detail = document["message"]
        raise BackendError(detail)
    return (result.stdout or result.stderr).strip()


def _load_document(path: Path, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise BackendError(f"backend succeeded without producing {path.name}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackendError(f"backend produced an invalid {description}: {exc}") from exc
    if not isinstance(document, dict):
        raise BackendError(f"backend produced an invalid {description}")
    return document


def _validate_plan(plan: dict[str, Any]) -> None:
    for field in ("directPackageTargets", "pendingItems", "unsupportedItems", "leafRequirements"):
        if not isinstance(plan.get(field), list):
            raise BackendError(f"backend plan is missing a valid {field} list")
    if not all(isinstance(value, str) for value in plan["directPackageTargets"]):
        raise BackendError("backend plan contains invalid directPackageTargets")
    if not all(isinstance(value, str) for value in plan["pendingItems"] + plan["unsupportedItems"]):
        raise BackendError("backend plan contains invalid pending or unsupported items")
    if not all(
        isinstance(item, dict) and item.get("status") in {"ready", "pending", "unsupported"}
        for item in plan["leafRequirements"]
    ):
        raise BackendError("backend plan contains invalid leafRequirements")


def load_inventory(
    catalog_path: Path,
    *,
    executable: str = "linxira-components",
    timeout: int = 30,
) -> dict[str, str]:
    resolved = shutil.which(executable)
    if resolved is None:
        return {}
    output = _run([
        resolved, "inventory", "--catalog", str(catalog_path),
    ], timeout=timeout)
    try:
        document = json.loads(output)
    except json.JSONDecodeError as exc:
        raise BackendError("backend produced an invalid installed-state inventory") from exc
    leaves = document.get("leaves") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != "org.linxira.components.installed-state.v1"
        or not isinstance(leaves, dict)
    ):
        raise BackendError("backend produced an invalid installed-state inventory")
    states: dict[str, str] = {}
    for leaf_id, value in leaves.items():
        state = value.get("state") if isinstance(value, dict) else None
        if isinstance(leaf_id, str) and state in {"installed", "partial", "absent", "unknown"}:
            states[leaf_id] = state
        else:
            raise BackendError("backend inventory contains an invalid leaf state")
    return states


def plan_selection(
    selection: dict[str, Any],
    catalog_path: Path,
    *,
    executable: str = "linxira-components",
    timeout: int = 30,
) -> Transaction:
    resolved = shutil.which(executable)
    if resolved is None:
        raise BackendError(f"backend executable not found: {executable}")
    transaction_dir = Path(tempfile.mkdtemp(prefix="linxira-component-manager-"))
    try:
        selection_path = transaction_dir / "selection.json"
        selection_path.write_text(
            json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _run([
            resolved,
            "plan",
            "--catalog",
            str(catalog_path),
            "--selection",
            str(selection_path),
            "--output-dir",
            str(transaction_dir),
        ], timeout=timeout)
        plan = _load_document(transaction_dir / "request-plan.json", "request plan")
        _validate_plan(plan)
        return Transaction(transaction_dir, plan, catalog_path, resolved)
    except Exception:
        shutil.rmtree(transaction_dir, ignore_errors=True)
        raise


def discard_transaction(transaction: Transaction) -> None:
    shutil.rmtree(transaction.directory, ignore_errors=True)


def confirm_and_apply(
    transaction: Transaction,
    *,
    pkexec: str = "pkexec",
    confirm_timeout: int = 30,
) -> ApplyResult:
    try:
        _run([
            transaction.executable,
            "confirm",
            "--catalog",
            str(transaction.catalog_path),
            "--plan",
            str(transaction.directory / "request-plan.json"),
            "--output-dir",
            str(transaction.directory),
        ], timeout=confirm_timeout)
        confirmation_path = transaction.directory / "confirmation.json"
        _load_document(confirmation_path, "confirmation")

        targets = transaction.plan["directPackageTargets"]
        requirements = transaction.plan["leafRequirements"]
        if not targets:
            ready_requirements = [item for item in requirements if item["status"] == "ready"]
            if any(item.get("packageTargets") for item in ready_requirements):
                raise BackendError(
                    "plan has no directPackageTargets but contains an unreconciled ready item"
                )
            if not ready_requirements:
                return ApplyResult(
                    "Plan confirmed. No executable package leaves require administrator authorization, so authorization was not requested; pending and unsupported items were not applied.",
                    False,
                )

        resolved_pkexec = shutil.which(pkexec)
        if resolved_pkexec is None:
            raise BackendError(f"authorization executable not found: {pkexec}")
        output = _run([
            resolved_pkexec,
            transaction.executable,
            "apply",
            "--confirmation",
            str(confirmation_path),
        ])
        return ApplyResult(output, True)
    finally:
        discard_transaction(transaction)
