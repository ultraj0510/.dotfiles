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
