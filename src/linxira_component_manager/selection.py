from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .catalog import Bundle, Catalog


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    path: tuple[str, ...]
    role: str
    origin: str


class SelectionModel:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.selected_bundles: set[str] = set()
        self.user_overrides: dict[str, bool] = {}
        self.explicit_paths: dict[str, set[tuple[str, ...]]] = {}

    def load_reconciled_paths(self, paths: Iterable[tuple[str, ...]]) -> None:
        reconciled = tuple(path for path in paths if path and path[-1] in self.catalog.leaves)
        selected_ids = {path[-1] for path in reconciled}
        roots = {path[0] for path in reconciled if path[0] in self.catalog.bundles}
        self.selected_bundles.update(roots)
        for root in roots:
            for leaf_id in self.catalog.leaf_ids(root) - selected_ids:
                self.user_overrides[leaf_id] = False
        for path in reconciled:
            if path and path[-1] in self.catalog.leaves:
                leaf_id = path[-1]
                self.user_overrides[leaf_id] = True
                self.explicit_paths.setdefault(leaf_id, set()).add(path)

    def _walk_bundle(
        self,
        bundle_id: str,
        path: tuple[str, ...],
        requests: dict[str, set[Request]],
        active_bundles: set[str],
    ) -> None:
        bundle = self.catalog.bundles[bundle_id]
        active_bundles.add(bundle_id)
        for child in bundle.children:
            child_path = path + (child.id,)
            override = self.user_overrides.get(child.id)
            selected = child.role == "required" or (child.role == "recommended" and override is not False)
            if bundle.policy != "preset" and child.role == "optional" and override is None:
                selected = True
            if override is True:
                selected = True
            if child.id in self.catalog.leaves:
                leaf = self.catalog.leaves[child.id]
                if selected and leaf.available:
                    requests.setdefault(child.id, set()).add(Request(child_path, child.role, bundle_id))
            elif selected:
                self._walk_bundle(child.id, child_path, requests, active_bundles)

    def evaluate(self) -> tuple[dict[str, set[Request]], set[str]]:
        requests: dict[str, set[Request]] = {}
        active_bundles: set[str] = set()
        for bundle_id in sorted(self.selected_bundles):
            self._walk_bundle(bundle_id, (bundle_id,), requests, active_bundles)
        for leaf_id, paths in self.explicit_paths.items():
            if self.user_overrides.get(leaf_id) is not False and self.catalog.leaves[leaf_id].available:
                for path in paths:
                    requests.setdefault(leaf_id, set()).add(Request(path, "user", "user"))
        return requests, active_bundles

    @property
    def selected_leaf_ids(self) -> frozenset[str]:
        return frozenset(self.evaluate()[0])

    def is_required(self, leaf_id: str) -> bool:
        requests = self.evaluate()[0].get(leaf_id, set())
        return any(request.role == "required" for request in requests)

    def _descendant_leaf_ids(self, node_id: str) -> frozenset[str]:
        return self.catalog.leaf_ids(node_id)

    def _selected_direct_children(self, bundle: Bundle, selected: set[str]) -> list[str]:
        return [
            child.id for child in bundle.children
            if selected.intersection(self._descendant_leaf_ids(child.id))
        ]

    def constraint_results(self) -> list[dict[str, object]]:
        selected = set(self.selected_leaf_ids)
        results: list[dict[str, object]] = []
        for bundle in self.catalog.bundles.values():
            chosen = self._selected_direct_children(bundle, selected)
            limit = 1 if bundle.policy == "exclusive" else bundle.max_selected
            valid = limit is None or len(chosen) <= limit
            results.append({
                "bundleId": bundle.id,
                "policy": bundle.policy,
                "selectedCount": len(chosen),
                "maxSelected": limit,
                "valid": valid,
            })
        return sorted(results, key=lambda result: str(result["bundleId"]))

    def _validate_constraints(self) -> None:
        invalid = [result for result in self.constraint_results() if not result["valid"]]
        if invalid:
            first = invalid[0]
            raise SelectionError(
                f"{first['bundleId']} allows at most {first['maxSelected']} selected child item(s)"
            )

    def _restore(self, snapshot: tuple[set[str], dict[str, bool], dict[str, set[tuple[str, ...]]]]) -> None:
        self.selected_bundles, self.user_overrides, self.explicit_paths = snapshot

    def _snapshot(self) -> tuple[set[str], dict[str, bool], dict[str, set[tuple[str, ...]]]]:
        return (
            set(self.selected_bundles),
            dict(self.user_overrides),
            {key: set(value) for key, value in self.explicit_paths.items()},
        )

    def set_bundle(self, bundle_id: str, selected: bool) -> None:
        if bundle_id not in self.catalog.bundles:
            raise SelectionError(f"unknown bundle: {bundle_id}")
        snapshot = self._snapshot()
        if selected:
            self.selected_bundles.add(bundle_id)
        else:
            self.selected_bundles.discard(bundle_id)
            prefix = (bundle_id,)
            for leaf_id in list(self.explicit_paths):
                self.explicit_paths[leaf_id] = {
                    path for path in self.explicit_paths[leaf_id] if path[:1] != prefix
                }
                if not self.explicit_paths[leaf_id]:
                    del self.explicit_paths[leaf_id]
        try:
            self._validate_constraints()
        except SelectionError:
            self._restore(snapshot)
            raise

    def _ancestor_bundles(self, path: tuple[str, ...]) -> Iterable[tuple[int, Bundle]]:
        for index, node_id in enumerate(path[:-1]):
            bundle = self.catalog.bundles.get(node_id)
            if bundle is not None:
                yield index, bundle

    def set_leaf(self, leaf_id: str, selected: bool, path: tuple[str, ...]) -> None:
        if leaf_id not in self.catalog.leaves or not path or path[-1] != leaf_id:
            raise SelectionError(f"invalid leaf selection path for {leaf_id}")
        leaf = self.catalog.leaves[leaf_id]
        if selected and not leaf.available:
            raise SelectionError(leaf.unavailable_reason or f"{leaf_id} is unavailable")
        if not selected and self.is_required(leaf_id):
            raise SelectionError(f"{leaf_id} is required by an active bundle")
        snapshot = self._snapshot()
        self.user_overrides[leaf_id] = selected
        if selected:
            if path[0] in self.catalog.bundles:
                self.selected_bundles.add(path[0])
            self.explicit_paths.setdefault(leaf_id, set()).add(path)
            for index, bundle in self._ancestor_bundles(path):
                if bundle.policy != "exclusive":
                    continue
                target_child = path[index + 1]
                for sibling in bundle.children:
                    if sibling.id == target_child:
                        continue
                    for sibling_leaf in self._descendant_leaf_ids(sibling.id):
                        self.user_overrides[sibling_leaf] = False
                        self.explicit_paths.pop(sibling_leaf, None)
        else:
            self.explicit_paths.pop(leaf_id, None)
        try:
            self._validate_constraints()
        except SelectionError:
            self._restore(snapshot)
            raise

    def node_state(self, node_id: str) -> int:
        selected = self.selected_leaf_ids
        leaves = {
            leaf_id for leaf_id in self._descendant_leaf_ids(node_id)
            if self.catalog.leaves[leaf_id].available
        }
        count = len(leaves.intersection(selected))
        if not count:
            return 0
        if count == len(leaves):
            return 2
        return 1

    def document(self) -> dict[str, object]:
        requests, active_bundles = self.evaluate()
        selected_ids = sorted(requests)
        leaves = []
        for leaf_id in selected_ids:
            paths = sorted({"/".join(request.path) for request in requests[leaf_id]})
            provenance = sorted({request.role for request in requests[leaf_id]})
            leaves.append({"id": leaf_id, "requestedBy": paths, "provenance": provenance})
        providers = sorted({self.catalog.leaves[leaf_id].provider for leaf_id in selected_ids})
        sources = sorted({self.catalog.leaves[leaf_id].source for leaf_id in selected_ids})
        return {
            "schemaVersion": "org.linxira.component-selection.v1",
            "catalogSha256": self.catalog.sha256,
            "catalogRelease": self.catalog.release,
            "selectedLeafIds": selected_ids,
            "selectedBundleIds": sorted(active_bundles),
            "leaves": leaves,
            "userOverrides": [
                {"id": node_id, "selected": selected}
                for node_id, selected in sorted(self.user_overrides.items())
            ],
            "constraintResults": self.constraint_results(),
            "providerRequirements": providers,
            "sourceRequirements": sources,
        }
