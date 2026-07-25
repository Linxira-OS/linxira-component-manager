# Quick System Runtime Setup

Independent PySide6 UI for selecting Linxira capability bundles, runtimes,
toolchains, and domain workspaces. It implements the Windows Features-style
expandable tri-state tree described by the Catalog v3 design baseline.

## Implemented behavior

- Reads Catalog v3 `components[]`, `applications[]`, `operations[]`, and `bundles[]` with stable IDs.
- Shows only top-level bundles whose `surface` is `components`; omitted `surface` defaults to `components`.
- Projects nested bundle DAGs as expandable trees and rejects direct or indirect cycles.
- Supports `required`, `recommended`, and `optional` child references.
- Supports `multi`, `exclusive`, `bounded`, and `preset` selection policies.
- Locks effective required leaves and reports why they cannot be cleared.
- Keys selection by stable leaf ID, de-duplicates repeated leaves, and records every
  effective `requestedBy` path.
- Derives unchecked, partial, and checked parent states from available descendants.
- Shows node metadata and a live selection document preview.
- Saves deterministic selection JSON and runs a complete plan/confirm/apply transaction.
- Keeps plan and apply subprocesses off the UI thread.
- Shows pending and unsupported leaves explicitly before confirmation; they are never applied.
- Phase 1 installs ready package targets only and does not support removal.

Unavailable leaves do not participate in parent state calculations and cannot be
selected. Exclusive policies clear sibling alternatives. Bounded policies reject a
change that would exceed `maxSelected`; they never silently truncate a selection.

## Catalog input

The canonical `linxira-catalog` contract is v3. This program consumes it directly
rather than translating v2 profiles or package arrays. The minimum root is:

```json
{
  "catalogVersion": 3,
  "release": "2026.07",
  "components": [],
  "bundles": []
}
```

Each leaf has `id`, `kind`, `name`, and optional descriptive/provider metadata.
Each bundle has `id`, `name`, `selection`, and `children`. `children` can be an object
with `required`, `recommended`, and `optional` arrays, or an array of `{id, role}`
objects. `selection` is a policy string or `{policy, maxSelected}` object. See
`examples/catalog-v3.example.json` for a complete nested example.

## Run

```console
python -m pip install -e .
linxira-component-manager examples/catalog-v3.example.json
```

Without an argument, the application checks
`/usr/share/linxira/catalog/catalog-v3.json`, then opens without data so the user can
choose a file with `Ctrl+O`.

## Transaction boundary

The manager never expands component IDs into package names and never invokes a package
manager directly. The **Plan with linxira-components** action performs this fixed flow:

1. Write the complete `org.linxira.component-selection.v1` document into a private temporary directory.
2. Run `linxira-components plan --catalog ... --selection ... --output-dir ...`.
3. Display the complete immutable `request-plan.json`, including separate pending and unsupported summaries.
4. After explicit user confirmation, run `linxira-components confirm` against that exact plan.
5. If `directPackageTargets` is non-empty, run `pkexec linxira-components apply --catalog ... --confirmation ...`.

Every subprocess uses a fixed argument vector and `shell=False`. Planning, confirmation,
authorization, and application run outside the UI thread. The transaction directory is
removed after cancellation, failure, or completion. A plan containing no direct package
targets and only pending/unsupported leaves is confirmed without requesting `pkexec`.
There is no `--component`, profile/application, package-manager, remove, or shell fallback.

## Test

Core parsing, cycle detection, stable-ID validation, nested selection, provenance,
constraints, required locking, backend transaction behavior, and the confirmation dialog
are tested with Qt's offscreen platform:

```console
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel --no-deps --wheel-dir dist .
```

The desktop entry is `data/org.linxira.ComponentManager.desktop`.
