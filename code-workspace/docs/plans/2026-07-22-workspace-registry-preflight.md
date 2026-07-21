# 工作区项目台账与预检治理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 manifest 完整登记所有一级项目仓库，并让 preflight 阻断治理入口缺失、未登记仓库及必要 remote 缺失。

**Architecture:** 保持 `[repos]` 字符串路径合同，新增平行的 `[repository_metadata]` 与 `[managed_links]`。preflight 在既有登记仓库检查之外，增加受限的一层仓库发现与符号链接来源校验，不递归、不自动修复。

**Tech Stack:** Python 3.11+、TOML、pytest、git、POSIX symlink。

## Global Constraints

- 不改变 `[repos]` 的字符串路径形状和 `--repo` 精确路径选择语义。
- JSON report `schema_version` 保持 1，避免提前破坏 taskctl 的严格检查。
- 只扫描 `runtime_view/repo` 的一级 Git 根，不递归扫描 worktree、fixture 或 vendor。
- 不创建 remote、不删除 worktree、不修改任何项目仓库内容。
- 新增或修改的提交信息和项目内部说明使用中文；外部协议字段保持既定英文。

---

### Task 1: 固定 manifest 新合同

**Files:**
- Modify: `tests/test_workspace_manifest.py`
- Modify: `code-workspace/workspace.toml`

**Interfaces:**
- Produces: `workspace.repository_root`、`managed_links`、`repository_metadata`，供 Task 2 的 checker 消费。

- [x] **Step 1: 先写失败测试**

在 `test_workspace_ownership_and_default_locations_are_explicit` 中断言：

```python
assert workspace["repository_root"] == "repo"
assert data["managed_links"] == {
    "scripts": {"path": "scripts", "source": "code-workspace/scripts"},
    "templates": {"path": "templates", "source": "code-workspace/templates"},
}
```

扩展 registry 测试，断言 `[repos]`、`[verification]`、`[repository_metadata]` key 相同且包含当前 8 个项目。

- [x] **Step 2: 验证测试先失败**

Run: `python3 -m pytest tests/test_workspace_manifest.py -q`

Expected: FAIL，缺少 `repository_root`、`managed_links`、metadata 与 2 个仍在维护范围内的仓库。

- [x] **Step 3: 最小实现 manifest**

在 `workspace.toml` 增加 `download_photos`、`cc_connect` 及对应 verification，并按设计文档登记 8 个 metadata。未固定统一命令的新增项目使用空数组。

- [x] **Step 4: 运行 manifest 测试**

Run: `python3 -m pytest tests/test_workspace_manifest.py -q`

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add code-workspace/workspace.toml tests/test_workspace_manifest.py
git commit -m "治理：补全工作区项目台账"
```

---

### Task 2: 实现 managed-link、仓库漂移和 remote 门禁

**Files:**
- Modify: `tests/test_workspace_preflight.py`
- Modify: `code-workspace/ai/checks/check_workspace.py`

**Interfaces:**
- Consumes: Task 1 的 manifest 合同。
- Produces: `MANAGED_LINK_MISSING`、`MANAGED_LINK_INVALID`、`UNREGISTERED_REPOSITORY`、`REPOSITORY_REQUIRED_REMOTE_MISSING` findings。

- [x] **Step 1: 扩展测试 manifest helper**

让 `write_manifest()` 创建 `repository_root`、managed-link source/target 和默认 metadata；允许测试覆盖 metadata 与 links。默认 metadata 为：

```python
{"kind": "test", "lifecycle": "active", "remote_policy": "optional"}
```

- [x] **Step 2: 写失败测试**

新增以下独立测试：

```python
def test_managed_links_must_exist_and_resolve_to_persistent_source(...): ...
def test_unregistered_direct_repository_is_blocked(...): ...
def test_repository_discovery_does_not_recurse_or_scan_outside_root(...): ...
def test_required_remote_is_blocked_and_optional_remote_is_allowed(...): ...
def test_upstream_remote_satisfies_required_policy(...): ...
def test_empty_verification_commands_are_silent(...): ...
def test_invalid_repository_metadata_is_manifest_error(...): ...
```

- [x] **Step 3: 验证测试先失败**

Run: `python3 -m pytest tests/test_workspace_preflight.py -q`

Expected: FAIL，缺少新 manifest 校验和 findings。

- [x] **Step 4: 实现严格 manifest 校验**

在 `validate_manifest()`：

- 要求 `workspace.repository_root` 为非空相对路径；
- 要求 `managed_links` 为非空 table，每项恰含 `path/source`；
- 要求 metadata 与 repos/verification 同 key；
- 校验 `lifecycle` 和 `remote_policy` 枚举。

- [x] **Step 5: 实现 managed-link 收集与判断**

在 workspace report 中加入每条 link 的 `path/source/status`，并在 `evaluate_report()` 将缺失或错误目标转成 BLOCKED finding。不得创建或修复链接。

- [x] **Step 6: 实现一级仓库发现**

新增只遍历 `runtime_view / repository_root` 一级子目录的函数。仅当子目录自身为 Git top-level 且未登记时生成 `UNREGISTERED_REPOSITORY`。

- [x] **Step 7: 实现 remote 与空 verification 语义**

`collect_repository()` 记录 `git remote` 列表；required 且列表为空时阻断。只对非空 verification 命令执行 `command_exists()` 和 unavailable finding。

- [x] **Step 8: 运行定向测试**

Run: `python3 -m pytest tests/test_workspace_preflight.py -q`

Expected: PASS。

- [x] **Step 9: 提交**

```bash
git add code-workspace/ai/checks/check_workspace.py tests/test_workspace_preflight.py
git commit -m "治理：阻断未登记仓库与失效入口"
```

---

### Task 3: 对齐文档并执行整体验证

**Files:**
- Modify: `code-workspace/workspace.md`
- Modify: `code-workspace/README.md`
- Modify: `code-workspace/docs/plans/2026-07-22-workspace-registry-preflight-design.md`
- Modify: `code-workspace/docs/plans/2026-07-22-workspace-registry-preflight.md`

**Interfaces:**
- Consumes: Tasks 1-2 的最终 manifest 与 preflight 行为。
- Produces: GitHub 审阅者可理解的边界与操作说明。

- [x] **Step 1: 更新项目台账说明**

在 `workspace.md` 说明 repository metadata、managed links、一级未登记仓库门禁，并补齐两个遗漏项目的职责分类。明确已废弃项目不进入台账。不得复制机器规则值之外的动态 Git 状态。

- [x] **Step 2: 更新 preflight 操作说明**

在 README 明确 preflight 同时检查登记仓库与 `repo/` 一级漂移；空 verification 表示未声明统一命令，不表示验证通过。

- [x] **Step 3: 自检文档**

Run:

```bash
rg -n "TBD|TODO|projects/|只检查.*manifest" code-workspace/workspace.md code-workspace/README.md code-workspace/docs/plans/2026-07-22-workspace-registry-preflight*.md
```

Expected: 无未解释的占位符或失效 `projects/` 路径。

- [x] **Step 4: 运行完整测试**

Run: `python3 -m pytest tests/test_workspace_manifest.py tests/test_workspace_preflight.py tests/test_task_protocol.py -q`

Expected: PASS，exit code 0。

- [x] **Step 5: 运行源码视图 preflight**

Run: `code-workspace/scripts/preflight --manifest code-workspace/workspace.toml --json`

Expected: 在链接尚未部署到 `/Users/fujie/code` 时明确返回 `MANAGED_LINK_MISSING` / BLOCKED；不得错误返回 PASS。

- [x] **Step 6: 提交**

```bash
git add code-workspace/workspace.md code-workspace/README.md code-workspace/docs/plans/2026-07-22-workspace-registry-preflight-design.md code-workspace/docs/plans/2026-07-22-workspace-registry-preflight.md
git commit -m "文档：说明项目台账与预检边界"
```

---

## Self-Review

- Spec coverage: 计划覆盖完整台账、managed links、一级仓库漂移、remote policy、空 verification 和文档更新。
- Placeholder scan: 没有 `TBD`、`TODO`、`implement later` 或未定义的后续工作占位。
- Type consistency: `repository_root`、`managed_links`、`repository_metadata`、`remote_policy` 名称在设计、测试和实现步骤中一致。
- Scope: taskctl 状态机、GitHub 远端变更和项目仓库清理均明确排除，保持单一审阅边界。
