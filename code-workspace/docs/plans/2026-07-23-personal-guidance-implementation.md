# Codex 与 Claude 个人规则统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将用户批准的完整个人规则作为 dotfiles 单一权威源，并让 Codex 与 Claude Code 在所有仓库中加载它。

**Architecture:** `agent-guidance/personal-workstyle.md` 保存完整规则；`install.sh` 将其链接为 Codex 全局 `AGENTS.md`，Claude 用户级 `CLAUDE.md` 通过 `@` 导入同一文件。项目级入口保持精简，只修正与个人规则直接冲突的源码标识语言说明。

**Tech Stack:** Markdown、Bash、Python 3、pytest、符号链接

## Global Constraints

- 个人规则移除标准 EOF 换行后的 SHA-256 必须为 `e77c16838ce1f632a9be4d1c1dfe3922e9d6d184f8a7e00089508efd35aaf40a`。
- Codex 与 Claude 必须读取同一份规则源，不维护两份手工副本。
- 保留 `code-workspace/CLAUDE.md` 中现有股票分析系统说明。
- 保留 `workspace.toml` 的 `commit_language = "zh"`。
- 不修改技能、插件、权限、代理定义或股票分析流程。
- 不覆盖来源不明的现有 `~/.codex/AGENTS.md` 符号链接。

---

### Task 1: 用失败测试固定个人规则和两个加载入口

**Files:**
- Create: `tests/test_personal_guidance.py`
- Test: `tests/test_personal_guidance.py`

**Interfaces:**
- Consumes: 现有 `install.sh` 的 `backup_and_link(src, dst, rel)` 行为。
- Produces: 权威源哈希、Claude 导入、工作区冲突消除、Codex 链接声明和
  `backup_and_link` 幂等/冲突行为的回归合同。

- [ ] **Step 1: 写入失败测试**

```python
import hashlib
import subprocess
from pathlib import Path


DOTFILES = Path(__file__).resolve().parents[1]
GUIDANCE = DOTFILES / "agent-guidance" / "personal-workstyle.md"
EXPECTED_SHA256 = "e77c16838ce1f632a9be4d1c1dfe3922e9d6d184f8a7e00089508efd35aaf40a"


def test_personal_guidance_matches_approved_content():
    content = GUIDANCE.read_bytes().removesuffix(b"\n")
    assert hashlib.sha256(content).hexdigest() == EXPECTED_SHA256


def test_claude_imports_the_shared_guidance_without_legacy_copy():
    text = (DOTFILES / "claude" / "CLAUDE.md").read_text()
    assert "@~/.dotfiles/agent-guidance/personal-workstyle.md" in text
    assert "<!-- User customizations -->" not in text
    project_text = (DOTFILES / "code-workspace" / "CLAUDE.md").read_text()
    assert "## 股票分析系统" in project_text


def test_workspace_has_no_conflicting_identifier_language_rule():
    text = (DOTFILES / "code-workspace" / "workspace.md").read_text()
    assert "新增或修改的内部源码标识使用中文" not in text
    assert "变量名、函数名、类型名、模块名等源码标识默认使用英文" in text


def run_backup_and_link(source: Path, destination: Path, relative: str):
    installer = (DOTFILES / "install.sh").read_text()
    function_definition = installer.split('echo "==> Installing dotfiles..."', 1)[0]
    script = function_definition + '\nbackup_and_link "$1" "$2" "$3"\n'
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            script,
            "backup_and_link",
            str(source),
            str(destination),
            relative,
        ],
        cwd=DOTFILES,
        check=False,
        capture_output=True,
        text=True,
    )


def test_installer_declares_codex_global_guidance_link():
    text = (DOTFILES / "install.sh").read_text()

    assert '"$DOTFILES/agent-guidance/personal-workstyle.md"' in text
    assert '"$HOME/.codex/AGENTS.md"' in text
    assert '"../.dotfiles/agent-guidance/personal-workstyle.md"' in text


def test_backup_and_link_creates_and_reuses_codex_link(tmp_path):
    destination = tmp_path / ".codex" / "AGENTS.md"
    relative = "../dotfiles/agent-guidance/personal-workstyle.md"
    source = tmp_path / "dotfiles" / "agent-guidance" / "personal-workstyle.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(GUIDANCE.read_bytes())

    first = run_backup_and_link(source, destination, relative)
    second = run_backup_and_link(source, destination, relative)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert destination.is_symlink()
    assert destination.resolve() == source.resolve()
    assert "skip (already linked):" in second.stdout


def test_backup_and_link_refuses_unknown_codex_symlink(tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    source = tmp_path / "managed-agents.md"
    source.write_text("# Managed")
    other = tmp_path / "other-agents.md"
    other.write_text("# Other")
    agents = codex_home / "AGENTS.md"
    agents.symlink_to(other)

    result = run_backup_and_link(source, agents, "../managed-agents.md")

    assert result.returncode == 2
    assert agents.resolve() == other.resolve()
    assert "BLOCKED: refusing to replace existing symlink" in result.stderr


def test_readme_documents_shared_guidance_and_codex_link():
    text = (DOTFILES / "README.md").read_text()
    assert "agent-guidance/personal-workstyle.md" in text
    assert "`~/.codex/AGENTS.md`" in text
    assert "@~/.dotfiles/agent-guidance/personal-workstyle.md" in text
```

- [ ] **Step 2: 运行测试并确认因权威源不存在而失败**

Run:

```bash
python3 -m pytest -p no:cacheprovider tests/test_personal_guidance.py -q
```

Expected: `test_personal_guidance_matches_approved_content` 因
`agent-guidance/personal-workstyle.md` 不存在而失败，其他新增合同也尚未满足。

- [ ] **Step 3: 提交测试合同**

```bash
git add tests/test_personal_guidance.py
git commit -m "测试：固定个人代理规则加载合同"
```

### Task 2: 建立单一规则源并接入 Codex 与 Claude

**Files:**
- Create: `agent-guidance/personal-workstyle.md`
- Modify: `install.sh`
- Modify: `claude/CLAUDE.md`
- Modify: `code-workspace/workspace.md:68-74`
- Test: `tests/test_personal_guidance.py`

**Interfaces:**
- Consumes: Task 1 的 SHA-256 和入口测试合同。
- Produces: `~/.codex/AGENTS.md` 链接目标及 Claude 用户级导入路径。

- [ ] **Step 1: 从批准附件复制权威源**

将
`/Users/fujie/.codex/attachments/32fd0265-bad9-4429-bc3e-882335cffaed/pasted-text.txt`
逐字复制为 `agent-guidance/personal-workstyle.md`，不改写内容或换行。

- [ ] **Step 2: 在安装脚本中增加 Codex 全局链接**

在 git 链接之后、Claude 链接之前加入：

```bash
# Codex 全局指令
mkdir -p "$HOME/.codex"
backup_and_link \
  "$DOTFILES/agent-guidance/personal-workstyle.md" \
  "$HOME/.codex/AGENTS.md" \
  "../.dotfiles/agent-guidance/personal-workstyle.md"
```

- [ ] **Step 3: 用单一导入替换 Claude 旧个人规则副本**

将用户级 `claude/CLAUDE.md:1-90` 的旧个人规则摘要整体替换为：

```markdown
@~/.dotfiles/agent-guidance/personal-workstyle.md

```

项目级 `code-workspace/CLAUDE.md` 不修改，其 `## 股票分析系统` 内容保持不变。

- [ ] **Step 4: 修正工作区源码标识语言冲突**

将 `code-workspace/workspace.md:71-73` 改为：

```markdown
- 变量名、函数名、类型名、模块名等源码标识默认使用英文。只有领域术语无法准确翻译且
  仓库已有明确约定时才使用中文标识。外部定义或已冻结的 API 名称、协议与 Schema 键、
  枚举与状态值、CLI 参数、文件路径、第三方名称及兼容性敏感标识必须保持其规定形式。
  不得为统一语言而批量重命名无关的既存标识。
```

- [ ] **Step 5: 运行定向测试并确认通过**

Run:

```bash
python3 -m pytest -p no:cacheprovider tests/test_personal_guidance.py -q
bash -n install.sh
```

Expected: `7 passed`，`bash -n` 返回 0。

- [ ] **Step 6: 提交规则和入口实现**

```bash
git add agent-guidance/personal-workstyle.md install.sh claude/CLAUDE.md \
  code-workspace/workspace.md
git commit -m "配置：统一 Codex 与 Claude 个人规则"
```

### Task 3: 更新 dotfiles 使用说明

**Files:**
- Modify: `README.md:25-60`
- Test: `tests/test_personal_guidance.py`

**Interfaces:**
- Consumes: Task 2 的 `agent-guidance/personal-workstyle.md` 和安装链接。
- Produces: 可审查的目录台账与安装链接说明。

- [ ] **Step 1: 更新目录树和安装链接表**

在 `README.md` 的管理对象目录树中增加：

```text
├── agent-guidance/
│   └── personal-workstyle.md    # Codex / Claude 共用个人规则
```

在安装链接表中增加：

```markdown
| `agent-guidance/personal-workstyle.md` | `~/.codex/AGENTS.md` |
```

并在表后说明 `claude/CLAUDE.md` 通过
`@~/.dotfiles/agent-guidance/personal-workstyle.md` 导入同一规则源。

- [ ] **Step 2: 运行定向测试**

Run:

```bash
python3 -m pytest -p no:cacheprovider tests/test_personal_guidance.py -q
```

Expected: `7 passed`。

- [ ] **Step 3: 提交文档**

```bash
git add README.md
git commit -m "文档：说明共享个人规则入口"
```

### Task 4: 完整验证与交付

**Files:**
- Verify: `agent-guidance/personal-workstyle.md`
- Verify: `install.sh`
- Verify: `claude/CLAUDE.md`
- Verify: `code-workspace/workspace.md`
- Verify: `README.md`
- Verify: `tests/test_personal_guidance.py`

**Interfaces:**
- Consumes: Tasks 1–3 的完整工作树。
- Produces: 任务关闭证据、可合并提交及安装后运行入口。

- [ ] **Step 1: 执行完整 dotfiles 测试与静态检查**

Run:

```bash
bash -n install.sh
python3 -m pytest -p no:cacheprovider tests -q
git diff --check main...HEAD
```

Expected: shell 语法通过；pytest 全部通过；`git diff --check` 无输出。

- [ ] **Step 2: 执行工作区 preflight**

在变更合并至 `/Users/fujie/.dotfiles/main` 后运行：

```bash
/Users/fujie/code/scripts/preflight --json
```

Expected: `status` 为 `PASS` 或仅包含已知、与本变更无关的 `WARN`；不得出现
`MANIFEST_INVALID`、`UNREGISTERED_REPOSITORY` 或失效 managed link。

- [ ] **Step 3: 安装并核对真实入口**

Run:

```bash
/Users/fujie/.dotfiles/install.sh
realpath /Users/fujie/.codex/AGENTS.md
realpath /Users/fujie/.claude/CLAUDE.md
```

Expected:

```text
/Users/fujie/.dotfiles/agent-guidance/personal-workstyle.md
/Users/fujie/.dotfiles/claude/CLAUDE.md
```

- [ ] **Step 4: 检查交付边界**

Run:

```bash
git status --short --branch
git log --oneline main..HEAD
git diff --stat main...HEAD
```

Expected: 工作树干净；提交只涉及设计、实施计划、个人规则入口、冲突修正、文档和测试。
