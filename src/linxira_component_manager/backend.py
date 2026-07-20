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
            statuses = {item["status"] for item in requirements}
            if not requirements or not statuses.issubset({"pending", "unsupported"}):
                raise BackendError(
                    "plan has no directPackageTargets but is not limited to pending/unsupported items"
                )
            return ApplyResult(
                "Plan confirmed. Pending and unsupported items were not applied; administrator authorization was not requested.",
                False,
            )

        resolved_pkexec = shutil.which(pkexec)
        if resolved_pkexec is None:
            raise BackendError(f"authorization executable not found: {pkexec}")
        output = _run([
            resolved_pkexec,
            transaction.executable,
            "apply",
            "--catalog",
            str(transaction.catalog_path),
            "--confirmation",
            str(confirmation_path),
        ])
        return ApplyResult(output, True)
    finally:
        discard_transaction(transaction)
