from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
POLICIES = {"multi", "exclusive", "bounded", "preset"}
ROLES = ("required", "recommended", "optional")
LEAF_KINDS = {"component", "application", "desktop", "operation"}
BUNDLE_SURFACES = {"applications", "components", "desktops"}


class CatalogError(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _text(value: Any, context: str) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        candidate = value.get("zh_CN") or value.get("en")
        if isinstance(candidate, str) and candidate:
            return candidate
    raise CatalogError(f"{context} must be a non-empty string or localized object")


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise CatalogError(f"invalid {context}: {value!r}")
    return value


@dataclass(frozen=True)
class Leaf:
    id: str
    kind: str
    name: str
    description: str
    provider: str
    source: str
    license: str
    available: bool
    unavailable_reason: str
    offline_policy: str

    @property
    def offline_label(self) -> str:
        return {
            "included": "镜像自带",
            "online-only": "需联网",
            "defer-with-consent": "可选延后",
        }.get(self.offline_policy, "")


@dataclass(frozen=True)
class ChildRef:
    id: str
    role: str


@dataclass(frozen=True)
class Bundle:
    id: str
    surface: str
    name: str
    description: str
    policy: str
    max_selected: int | None
    children: tuple[ChildRef, ...]


@dataclass(frozen=True)
class Catalog:
    path: Path
    sha256: str
    release: str
    leaves: dict[str, Leaf]
    bundles: dict[str, Bundle]
    top_level_bundle_ids: tuple[str, ...]

    def node_name(self, node_id: str) -> str:
        node = self.leaves.get(node_id) or self.bundles.get(node_id)
        if node is None:
            raise KeyError(node_id)
        return node.name

    def leaf_ids(self, node_id: str) -> frozenset[str]:
        found: set[str] = set()

        def visit(current: str) -> None:
            if current in self.leaves:
                found.add(current)
                return
            for child in self.bundles[current].children:
                visit(child.id)

        visit(node_id)
        return frozenset(found)


def _parse_children(raw: Any, context: str) -> tuple[ChildRef, ...]:
    refs: list[ChildRef] = []
    if isinstance(raw, dict):
        unknown = set(raw) - set(ROLES)
        if unknown:
            raise CatalogError(f"{context} has unknown roles: {', '.join(sorted(unknown))}")
        for role in ROLES:
            values = raw.get(role, [])
            if not isinstance(values, list):
                raise CatalogError(f"{context}.{role} must be an array")
            refs.extend(ChildRef(_identifier(value, f"{context}.{role} item"), role) for value in values)
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            if not isinstance(value, dict) or set(value) != {"id", "role"}:
                raise CatalogError(f"{context}[{index}] must contain exactly id and role")
            role = value["role"]
            if role not in ROLES:
                raise CatalogError(f"invalid {context}[{index}].role")
            refs.append(ChildRef(_identifier(value["id"], f"{context}[{index}].id"), role))
    else:
        raise CatalogError(f"{context} must be an object or array")
    ids = [ref.id for ref in refs]
    if not refs:
        raise CatalogError(f"{context} must not be empty")
    if len(ids) != len(set(ids)):
        raise CatalogError(f"{context} contains duplicate references")
    return tuple(refs)


def load_catalog(path: str | Path) -> Catalog:
    catalog_path = Path(path)
    try:
        raw = catalog_path.read_bytes()
    except OSError as exc:
        raise CatalogError(f"cannot read catalog {catalog_path}: {exc}") from exc
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"invalid UTF-8 JSON catalog: {exc}") from exc
    if not isinstance(document, dict):
        raise CatalogError("catalog root must be an object")
    if document.get("catalogVersion") != 3 or isinstance(document.get("catalogVersion"), bool):
        raise CatalogError("catalogVersion must be integer 3")
    release = _text(document.get("release", "v3-development"), "release")

    raw_components = document.get("components", [])
    raw_applications = document.get("applications", [])
    raw_desktops = document.get("desktops", [])
    raw_operations = document.get("operations", [])
    raw_bundles = document.get("bundles", [])
    if not all(isinstance(collection, list) for collection in (
        raw_components, raw_applications, raw_desktops, raw_operations, raw_bundles
    )):
        raise CatalogError("components, applications, desktops, operations, and bundles must be arrays")

    leaves: dict[str, Leaf] = {}
    collections = (
        ("components", raw_components, "component"),
        ("applications", raw_applications, "application"),
        ("desktops", raw_desktops, "desktop"),
        ("operations", raw_operations, "operation"),
    )
    for collection_name, collection, default_kind in collections:
        for index, item in enumerate(collection):
            context = f"{collection_name}[{index}]"
            if not isinstance(item, dict):
                raise CatalogError(f"{context} must be an object")
            leaf_id = _identifier(item.get("id"), f"{context}.id")
            kind = item.get("kind", default_kind)
            if kind != default_kind:
                raise CatalogError(f"invalid {context}.kind")
            if leaf_id in leaves:
                raise CatalogError(f"duplicate stable ID: {leaf_id}")
            availability = item.get("availability", True)
            if isinstance(availability, bool):
                available, reason = availability, ""
            elif isinstance(availability, dict):
                if isinstance(availability.get("available"), bool):
                    available = availability["available"]
                elif availability.get("status") in {"available", "review-channel", "unavailable"}:
                    # review-channel items (source/legal review pending) must
                    # not be selectable; only plain "available" is installable.
                    available = availability["status"] == "available"
                else:
                    raise CatalogError(f"invalid {context}.availability")
                reason = str(availability.get("reason", ""))
            else:
                raise CatalogError(f"invalid {context}.availability")
            offline_policy = str(availability.get("offlinePolicy", "")) if isinstance(availability, dict) else ""
            license_value = item.get("license", "unspecified")
            if isinstance(license_value, dict):
                license_value = license_value.get("spdx", "unspecified")
            leaves[leaf_id] = Leaf(
                id=leaf_id,
                kind=kind,
                name=_text(item.get("name"), f"{context}.name"),
                description=_text(item.get("description", item.get("name")), f"{context}.description"),
                provider=str(item.get("provider", "unspecified")),
                source=str(item.get("source", "unspecified")),
                license=str(license_value),
                available=available,
                unavailable_reason=reason,
                offline_policy=offline_policy,
            )

    bundles: dict[str, Bundle] = {}
    for index, item in enumerate(raw_bundles):
        context = f"bundles[{index}]"
        if not isinstance(item, dict):
            raise CatalogError(f"{context} must be an object")
        bundle_id = _identifier(item.get("id"), f"{context}.id")
        if bundle_id in leaves or bundle_id in bundles:
            raise CatalogError(f"duplicate stable ID: {bundle_id}")
        selection = item.get("selection", "preset")
        if isinstance(selection, str):
            policy, max_selected = selection, item.get("maxSelected")
        elif isinstance(selection, dict):
            policy = selection.get("policy", selection.get("mode"))
            max_selected = selection.get("maxSelected")
        else:
            raise CatalogError(f"invalid {context}.selection")
        if policy not in POLICIES:
            raise CatalogError(f"invalid {context} selection policy")
        if policy == "bounded":
            if not isinstance(max_selected, int) or isinstance(max_selected, bool) or max_selected < 1:
                raise CatalogError(f"{context} bounded selection requires positive maxSelected")
        elif max_selected is not None:
            raise CatalogError(f"{context} maxSelected is only valid for bounded selection")
        surface = item.get("surface", "components")
        if not isinstance(surface, str) or surface not in BUNDLE_SURFACES:
            raise CatalogError(f"invalid {context}.surface")
        bundles[bundle_id] = Bundle(
            id=bundle_id,
            surface=surface,
            name=_text(item.get("name"), f"{context}.name"),
            description=_text(item.get("description", item.get("name")), f"{context}.description"),
            policy=policy,
            max_selected=max_selected,
            children=_parse_children(item.get("children"), f"{context}.children"),
        )

    known = set(leaves) | set(bundles)
    referenced_bundles: set[str] = set()
    for bundle in bundles.values():
        unknown = sorted({child.id for child in bundle.children} - known)
        if unknown:
            raise CatalogError(f"bundle {bundle.id} references unknown IDs: {', '.join(unknown)}")
        referenced_bundles.update(child.id for child in bundle.children if child.id in bundles)

    visiting: list[str] = []
    visited: set[str] = set()

    def check_cycle(bundle_id: str) -> None:
        if bundle_id in visiting:
            cycle = visiting[visiting.index(bundle_id):] + [bundle_id]
            raise CatalogError(f"bundle cycle detected: {' -> '.join(cycle)}")
        if bundle_id in visited:
            return
        visiting.append(bundle_id)
        for child in bundles[bundle_id].children:
            if child.id in bundles:
                check_cycle(child.id)
        visiting.pop()
        visited.add(bundle_id)

    for bundle_id in bundles:
        check_cycle(bundle_id)
    roots = tuple(bundle_id for bundle_id in bundles if bundle_id not in referenced_bundles)
    if bundles and not roots:
        raise CatalogError("catalog has no top-level bundle")
    top_level = tuple(bundle_id for bundle_id in roots if bundles[bundle_id].surface == "components")
    return Catalog(
        path=catalog_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        release=release,
        leaves=leaves,
        bundles=bundles,
        top_level_bundle_ids=top_level,
    )
