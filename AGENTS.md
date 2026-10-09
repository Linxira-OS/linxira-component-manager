# linxira-component-manager · Agent 开发规范

> **档位**:A 档 · 系统源仓(带 `VERSION` + `.github/workflows/release.yml`)。
> **本仓职责**:独立的 PySide6 UI,以「Windows 功能启用」风格的三态树选择 Linxira 能力 bundle / runtime / toolchain / 领域工作区。
> 通用条款见工作区总纲 `f:\Linxira-OS\AGENTS.md`;发布/测试口径见 `linxira-os/docs/RELEASE_STANDARD.md`。本文件只写本仓特有约定。

## 职责与边界

- **负责**:直接消费 Catalog v3 的 `components[]` / `applications[]` / `operations[]` / `bundles[]`;把嵌套 bundle DAG 投影为可展开树并拒绝环;支持 `required`/`recommended`/`optional` 与 `multi`/`exclusive`/`bounded`/`preset` 选择策略;以稳定叶子 ID 为键;生成确定性 selection JSON;展示 plan 并执行完整事务。
- **UI 只调用,不实现交易逻辑**:本管理器**从不把组件 ID 展开为包名、从不直接调用包管理器**。固定流程:
  1. 把 `org.linxira.component-selection.v1` 文档写入私有临时目录;
  2. `linxira-components plan --catalog ... --selection ... --output-dir ...`;
  3. 展示不可变 `request-plan.json`(含 pending / unsupported 汇总);
  4. 用户显式确认后 `linxira-components confirm`;
  5. `directPackageTargets` 非空时 `pkexec linxira-components apply --catalog ... --confirmation ...`。
- **提权只走 `linxira-components` + polkit**;本仓不得重新实现提权,子进程一律固定参数向量 + `shell=False`。
- 不负责:catalog 数据(归 `linxira-catalog`)、事务后端(归 `linxira-components`)。

## 目录布局

```
src/linxira_component_manager/  app.py / ui.py / catalog.py / selection.py
                                backend.py / cli.py / tui.py / about.py
data/                           org.linxira.ComponentManager.desktop / .metainfo.xml
examples/catalog-v3.example.json
tests/                          test_ui / test_catalog / test_selection / test_backend / test_cli
```

## 本地校验

Qt 使用 offscreen 平台:

```sh
python -m pip install -e .
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel --no-deps --wheel-dir dist .
```

CI(`.github/workflows/ci.yml`,Python 3.11)另装 `libegl1`,并以 `QT_QPA_PLATFORM=offscreen` 跑上面前三项,最后校验 **`VERSION` 与 `pyproject.toml` version 一致**。

## 目录输入与运行

- 规范契约是 Catalog v3;默认查找 `/usr/share/linxira/catalog/catalog-v3.json`,无参启动可 `Ctrl+O` 选文件。
- 运行:`linxira-component-manager examples/catalog-v3.example.json`。

## 版本与发布

- 版本唯一来源是根目录 `VERSION`(当前 0.1.5);`pyproject.toml` version 必须同步(CI 会拒)。
- CLI 入口:`linxira-component-manager = linxira_component_manager.app:main`(依赖 `PySide6>=6.7`,Python ≥ 3.11)。
- 提交 `VERSION` 变更即触发 `.github/workflows/release.yml` 走全自动发布链。**禁止手工 bump**。

## 禁区

- 不得新增 `--component`、profile/application、包管理器、remove 或 shell 回退路径。
- 不得把 plan/confirm/apply 放到 UI 线程执行;事务目录在取消/失败/完成后必须移除。
- 不可用叶子不参与父状态计算、不可选中;第 1 阶段只安装就绪包目标,**不支持移除**。
- 只在显式用户确认后请求 `pkexec`;纯 pending/unsupported 的计划确认时不得请求提权。