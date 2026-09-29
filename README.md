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

---

## 简体中文

用于选择 Linxira 能力捆绑包、运行时、工具链和领域工作区的独立 PySide6
图形界面。它实现了 Catalog v3 设计基线所描述的、类似 Windows「功能启用」
风格的可展开三态树。

### 已实现的行为

- 读取 Catalog v3 的 `components[]`、`applications[]`、`operations[]` 和
  `bundles[]`，并使用稳定 ID。
- 仅显示 `surface` 为 `components` 的顶层捆绑包；省略 `surface` 时默认为
  `components`。
- 将嵌套捆绑包 DAG 投影为可展开的树，并拒绝直接或间接的循环。
- 支持 `required`、`recommended` 和 `optional` 子引用。
- 支持 `multi`、`exclusive`、`bounded` 和 `preset` 选择策略。
- 锁定生效的必需叶子节点，并说明它们为何无法被清除。
- 以稳定叶子 ID 作为选择键，对重复叶子去重，并记录每一条生效的
  `requestedBy` 路径。
- 根据可见后代派生父节点的未选、部分选中和全选状态。
- 显示节点元数据和实时选择文档预览。
- 保存确定性的选择 JSON，并执行完整的 plan/confirm/apply 事务。
- 使 plan 与 apply 子进程不占用 UI 线程。
- 在确认之前明确显示 pending 与 unsupported 叶子；它们永远不会被应用。
- 第 1 阶段仅安装就绪的软件包目标，不支持移除。

不可用的叶子不参与父节点状态计算，也无法被选中。exclusive 策略会清除同级的
互斥选项。bounded 策略会拒绝超过 `maxSelected` 的变更，绝不会静默截断选择。

### Catalog 输入

规范的 `linxira-catalog` 契约为 v3。本程序直接消费该格式，而不是转换 v2 的
profile 或包数组。最小的根结构为：

```json
{
  "catalogVersion": 3,
  "release": "2026.07",
  "components": [],
  "bundles": []
}
```

每个叶子具有 `id`、`kind`、`name` 以及可选的描述/提供者元数据。每个捆绑包
具有 `id`、`name`、`selection` 和 `children`。`children` 可以是包含
`required`、`recommended`、`optional` 数组的对象，也可以是 `{id, role}` 对象
数组。`selection` 是策略字符串或 `{policy, maxSelected}` 对象。完整的嵌套
示例见 `examples/catalog-v3.example.json`。

### 运行

```console
python -m pip install -e .
linxira-component-manager examples/catalog-v3.example.json
```

不带参数时，应用程序会先检查
`/usr/share/linxira/catalog/catalog-v3.json`，然后在没有数据的情况下启动，
用户可用 `Ctrl+O` 选择文件。

### 事务边界

本管理器从不把组件 ID 展开为软件包名，也从不直接调用包管理器。「Plan with
linxira-components」动作执行以下固定流程：

1. 将完整的 `org.linxira.component-selection.v1` 文档写入私有的临时目录。
2. 运行 `linxira-components plan --catalog ... --selection ... --output-dir ...`。
3. 显示完整且不可变的 `request-plan.json`，包括独立的 pending 与 unsupported
   汇总。
4. 在用户显式确认后，针对该确切计划运行 `linxira-components confirm`。
5. 若 `directPackageTargets` 非空，运行
   `pkexec linxira-components apply --catalog ... --confirmation ...`。

每个子进程都使用固定参数向量并设置 `shell=False`。计划、确认、授权和应用都
在 UI 线程之外运行。事务目录在取消、失败或完成后都会被移除。若计划不含直接
软件包目标、只包含 pending/unsupported 叶子，则无需请求 `pkexec` 即可确认。
不存在 `--component`、profile/application、包管理器、移除或 shell 回退。

### 测试

核心解析、循环检测、稳定 ID 校验、嵌套选择、来源追踪、约束、必需锁定、后端
事务行为以及确认对话框均使用 Qt offscreen 平台测试：

```console
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel --no-deps --wheel-dir dist .
```

桌面入口文件为 `data/org.linxira.ComponentManager.desktop`。
