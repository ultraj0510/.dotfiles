import tomllib
from pathlib import Path


DOTFILES = Path(__file__).resolve().parents[1]
MANIFEST = DOTFILES / "code-workspace" / "workspace.toml"
ACTIVE_DOCS = (
    DOTFILES / "README.md",
    DOTFILES / "code-workspace" / "AGENTS.md",
    DOTFILES / "code-workspace" / "CLAUDE.md",
    DOTFILES / "code-workspace" / "README.md",
    DOTFILES / "code-workspace" / "workspace.md",
    DOTFILES / "code-workspace" / "docs" / "plans" / "README.md",
)


def load_manifest():
    return tomllib.loads(MANIFEST.read_text())


def test_workspace_ownership_and_default_locations_are_explicit():
    data = load_manifest()
    workspace = data["workspace"]

    assert workspace["source_repository"] == "/Users/fujie/.dotfiles"
    assert workspace["runtime_view"] == "/Users/fujie/code"
    assert workspace["root"] == workspace["runtime_view"]
    assert workspace["repository_root"] == "repo"
    assert "source_of_truth" not in workspace
    assert workspace["human_documentation"] == "workspace.md"
    assert workspace["default_task_dir"] == "runtime/tasks"
    assert workspace["default_plan_dir"] == "docs/plans"
    assert workspace["default_archive_dir"] == "docs/archive"
    assert workspace["default_lessons_file"] == "docs/lessons.md"
    assert data["rules"]["commit_language"] == "zh"
    assert data["managed_links"] == {
        "scripts": {"path": "scripts", "source": "code-workspace/scripts"},
        "templates": {"path": "templates", "source": "code-workspace/templates"},
    }
    assert len(
        {
            workspace["default_task_dir"],
            workspace["default_plan_dir"],
            workspace["default_archive_dir"],
        }
    ) == 3


def test_registered_workspace_paths_exist():
    data = load_manifest()
    runtime_view = Path(data["workspace"]["runtime_view"])

    relative_paths = [
        data["workspace"]["human_documentation"],
        data["workspace"]["default_task_dir"],
        data["workspace"]["default_plan_dir"],
        data["workspace"]["default_archive_dir"],
        data["workspace"]["default_lessons_file"],
        *data["tools"].values(),
        *data["runtime"].values(),
        *data["repos"].values(),
        *data["references"].values(),
        *data["generated"].values(),
    ]

    assert Path(data["workspace"]["source_repository"]).is_dir()
    for relative in relative_paths:
        assert (runtime_view / relative).exists(), relative

    runtime_manifest = runtime_view / "workspace.toml"
    expected_manifest = (
        Path(data["workspace"]["source_repository"])
        / "code-workspace"
        / "workspace.toml"
    )
    assert runtime_manifest.is_symlink()
    assert runtime_manifest.resolve() == expected_manifest.resolve()

    for repo_key, commands in data["verification"].items():
        repo = runtime_view / data["repos"][repo_key]
        if commands["test_command"]:
            assert (repo / commands["test_command"][0]).is_file(), repo_key


def test_repository_registry_has_one_current_name_per_repository():
    data = load_manifest()
    expected_repositories = {
        "stock_analysis",
        "playground",
        "tradingagents",
        "claude_code_best_practice",
        "nikkei_research_os",
        "nikkei225_factor_lab",
        "download_photos",
        "cc_connect",
    }

    assert "projects" not in data
    assert data["repos"]["stock_analysis"] == "repo/stock-analysis"
    assert "stock_price_analyze" not in data["repos"]
    assert "codexpro" not in data["repos"]
    assert len(data["repos"].values()) == len(set(data["repos"].values()))
    assert set(data["repos"]) == expected_repositories
    assert set(data["verification"]) == set(data["repos"])
    assert set(data["repository_metadata"]) == set(data["repos"])

    for commands in data["verification"].values():
        assert set(commands) == {"test_command", "verify_command"}
        assert isinstance(commands["test_command"], list)
        assert isinstance(commands["verify_command"], list)


def test_active_docs_reference_manifest_without_redefining_machine_rules():
    text = "\n".join(path.read_text() for path in ACTIVE_DOCS)

    assert "repo/stock-price-analyze" not in text
    assert "repo/codexpro" not in text
    assert "提交信息使用中文" not in text
    assert "commit messages in English" not in text
    assert "source of truth for project structure" not in text
    assert "项目结构和共享规则的唯一事实来源" not in text
    assert "workspace.toml" in text
    assert "[rules]" in text

    for name in ("AGENTS.md", "CLAUDE.md"):
        entrypoint = (DOTFILES / "code-workspace" / name).read_text()
        assert "workspace.md" in entrypoint
        assert "workspace.toml" in entrypoint
