import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "code-workspace" / "ai" / "checks" / "check_workspace.py"
PREFLIGHT = ROOT / "code-workspace" / "scripts" / "preflight"
INSTALL_LINKS = ROOT / "code-workspace" / "scripts" / "install-links"


def load_checker():
    spec = importlib.util.spec_from_file_location("workspace_preflight", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args, cwd=None, check=True):
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def git(path, *args):
    return run("git", *args, cwd=path).stdout.strip()


def init_repo(path, *, commit=True):
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "preflight@example.invalid")
    git(path, "config", "user.name", "Preflight Test")
    if commit:
        (path / "tracked.txt").write_text("base\n")
        git(path, "add", "tracked.txt")
        git(path, "commit", "-qm", "base")
    return path


def write_manifest(tmp_path, repos, verification=None):
    runtime = tmp_path / "runtime view"
    source = tmp_path / "dotfiles source"
    source_workspace = source / "code-workspace"
    source_workspace.mkdir(parents=True)
    runtime.mkdir(exist_ok=True)
    (runtime / "workspace.md").write_text("guide\n")
    for relative in ("runtime/tasks", "docs/plans", "docs/archive"):
        (runtime / relative).mkdir(parents=True)
    (runtime / "docs/lessons.md").write_text("lessons\n")

    repo_lines = "\n".join(
        f'{name} = "{path.relative_to(runtime).as_posix()}"'
        for name, path in repos.items()
    )
    verification = verification or {
        name: {"test_command": ["git", "status"], "verify_command": ["git", "status"]}
        for name in repos
    }
    verification_lines = []
    for name, commands in verification.items():
        verification_lines.extend(
            [
                f"[verification.{name}]",
                f'test_command = {json.dumps(commands["test_command"])}',
                f'verify_command = {json.dumps(commands["verify_command"])}',
                "",
            ]
        )

    manifest = source_workspace / "workspace.toml"
    manifest.write_text(
        f'''[workspace]
root = "{runtime}"
runtime_view = "{runtime}"
source_repository = "{source}"
human_documentation = "workspace.md"
default_task_dir = "runtime/tasks"
default_plan_dir = "docs/plans"
default_archive_dir = "docs/archive"
default_lessons_file = "docs/lessons.md"

[rules]
commit_language = "zh"

[repos]
{repo_lines}

{"\n".join(verification_lines)}'''
    )
    os.symlink(manifest, runtime / "workspace.toml")
    return runtime / "workspace.toml"


def test_report_schema_and_renderers_share_one_result(tmp_path):
    checker = load_checker()
    runtime = tmp_path / "runtime view"
    repo = init_repo(runtime / "repo" / "sample")
    manifest = write_manifest(tmp_path, {"sample": repo})

    report = checker.build_report(manifest)
    rendered = checker.render_human(report)
    encoded = json.loads(checker.render_json(report))

    assert list(report) == [
        "schema_version",
        "status",
        "workspace",
        "repositories",
        "artifacts",
        "findings",
    ]
    assert report["schema_version"] == 1
    assert encoded == report
    assert f"status={report['status']}" in rendered
    assert [item["code"] for item in encoded["findings"]] == [
        item["code"] for item in report["findings"]
    ]


def test_legacy_checker_defaults_to_manifest_beside_its_implementation():
    checker = load_checker()
    args = checker.parse_args([])

    assert args.manifest == ROOT / "code-workspace" / "workspace.toml"


@pytest.mark.parametrize(
    ("status", "expected"),
    [("PASS", 0), ("WARN", 1), ("BLOCKED", 2), ("ERROR", 3)],
)
def test_status_exit_code_contract(status, expected):
    checker = load_checker()
    assert checker.exit_code(status) == expected


def test_final_status_uses_deterministic_highest_severity():
    checker = load_checker()
    warn = checker.make_finding("WARN_TEST", "WARN", "test", "warn")
    blocked = checker.make_finding("BLOCK_TEST", "BLOCKED", "test", "blocked")
    error = checker.make_finding("ERROR_TEST", "ERROR", "test", "error")

    assert checker.evaluate_report({}, [], [warn])["status"] == "WARN"
    assert checker.evaluate_report({}, [], [warn, blocked])["status"] == "BLOCKED"
    assert checker.evaluate_report({}, [], [error, warn, blocked])["status"] == "ERROR"


def test_collect_repository_clean_dirty_staged_unstaged_and_untracked(tmp_path):
    checker = load_checker()
    repo = init_repo(tmp_path / "repo with spaces")

    clean = checker.collect_repository("sample", repo, {})
    assert clean["dirty"] is False
    assert clean["staged"] == []
    assert clean["unstaged"] == []
    assert clean["untracked"] == []

    (repo / "tracked.txt").write_text("unstaged\n")
    (repo / "staged.txt").write_text("staged\n")
    (repo / "untracked.txt").write_text("untracked\n")
    git(repo, "add", "staged.txt")
    dirty = checker.collect_repository("sample", repo, {})

    assert dirty["dirty"] is True
    assert dirty["staged"] == ["staged.txt"]
    assert dirty["unstaged"] == ["tracked.txt"]
    assert dirty["untracked"] == ["untracked.txt"]


def test_non_executable_verification_command_is_unavailable(tmp_path):
    checker = load_checker()
    repo = init_repo(tmp_path / "repo")
    command = repo / "verify"
    command.write_text("#!/bin/sh\n")

    facts = checker.collect_repository(
        "sample",
        repo,
        {"test_command": ["./verify"], "verify_command": []},
    )

    assert facts["verification"]["test_command_exists"] is False


def test_collect_repository_ahead_and_behind(tmp_path):
    checker = load_checker()
    remote = tmp_path / "remote.git"
    run("git", "init", "--bare", "-q", str(remote))
    seed = init_repo(tmp_path / "seed")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-qu", "origin", "HEAD")
    branch = git(seed, "branch", "--show-current")

    peer = tmp_path / "peer"
    run("git", "clone", "-q", str(remote), str(peer))
    git(peer, "config", "user.email", "preflight@example.invalid")
    git(peer, "config", "user.name", "Preflight Test")
    (peer / "peer.txt").write_text("peer\n")
    git(peer, "add", "peer.txt")
    git(peer, "commit", "-qm", "peer")
    git(peer, "push", "-q")

    (seed / "local.txt").write_text("local\n")
    git(seed, "add", "local.txt")
    git(seed, "commit", "-qm", "local")
    git(seed, "fetch", "-q", "origin")
    facts = checker.collect_repository("sample", seed, {})

    assert facts["branch"] == branch
    assert facts["upstream"] == f"origin/{branch}"
    assert facts["ahead"] == 1
    assert facts["behind"] == 1


def test_collect_repository_without_upstream_and_detached_head(tmp_path):
    checker = load_checker()
    repo = init_repo(tmp_path / "repo")

    no_upstream = checker.collect_repository("sample", repo, {})
    assert no_upstream["upstream"] is None
    assert no_upstream["ahead"] is None
    assert no_upstream["behind"] is None

    git(repo, "checkout", "-q", "--detach")
    detached = checker.collect_repository("sample", repo, {})
    assert detached["detached"] is True
    assert detached["branch"] is None


def test_missing_and_non_git_repository_are_findings(tmp_path):
    checker = load_checker()
    missing = checker.collect_repository("missing", tmp_path / "missing", {})
    plain = tmp_path / "plain"
    plain.mkdir()
    non_git = checker.collect_repository("plain", plain, {})

    assert missing["collection_status"] == "MISSING"
    assert non_git["collection_status"] == "NOT_GIT"
    report = checker.evaluate_report({}, [missing, non_git])
    assert report["status"] == "BLOCKED"
    assert {item["code"] for item in report["findings"]} == {
        "REPOSITORY_PATH_MISSING",
        "REPOSITORY_NOT_GIT",
    }


def test_nested_directory_is_not_accepted_as_repository_root(tmp_path):
    checker = load_checker()
    parent = init_repo(tmp_path / "parent")
    nested = parent / "nested"
    nested.mkdir()

    facts = checker.collect_repository("nested", nested, {})

    assert facts["collection_status"] == "NOT_GIT"


def test_corrupt_git_metadata_is_collection_error(tmp_path):
    checker = load_checker()
    repo = tmp_path / "corrupt"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: missing-worktree-metadata\n")

    facts = checker.collect_repository("corrupt", repo, {})
    report = checker.evaluate_report({}, [facts])

    assert facts["collection_status"] == "ERROR"
    assert report["status"] == "ERROR"
    assert report["findings"][0]["code"] == "GIT_COMMAND_FAILED"


def test_git_command_failure_is_error(tmp_path, monkeypatch):
    checker = load_checker()
    repo = init_repo(tmp_path / "repo")

    def fail_git(*args, **kwargs):
        raise checker.GitCollectionError("simulated failure")

    monkeypatch.setattr(checker, "run_git", fail_git)
    facts = checker.collect_repository("sample", repo, {})
    report = checker.evaluate_report({}, [facts])

    assert report["status"] == "ERROR"
    assert report["findings"][0]["code"] == "GIT_COMMAND_FAILED"


def test_artifacts_only_use_untracked_git_facts(tmp_path):
    checker = load_checker()
    repo = init_repo(tmp_path / "repo")
    fixture = repo / "tests" / "fixtures" / "outputs" / "golden.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{}\n")
    git(repo, "add", str(fixture.relative_to(repo)))
    git(repo, "commit", "-qm", "fixture")
    artifact = repo / "outputs" / "run.json"
    artifact.parent.mkdir()
    artifact.write_text("{}\n")
    cache = repo / ".venv" / "cache.bin"
    cache.parent.mkdir()
    cache.write_text("cache\n")
    (repo / ".gitignore").write_text(".venv/\n")

    facts = checker.collect_repository("sample", repo, {})
    report = checker.evaluate_report({}, [facts])

    assert facts["untracked"] == [".gitignore", "outputs/"]
    assert report["artifacts"]["suspicious_untracked"] == [
        {
            "repository": "sample",
            "kind": "generated_output",
            "path": "outputs/",
            "rule": "untracked path under outputs/",
        }
    ]
    assert "tests/fixtures/outputs/golden.json" not in json.dumps(report)
    assert ".venv/cache.bin" not in json.dumps(report)


def test_invalid_manifest_is_error_and_missing_registered_path_is_blocked(tmp_path):
    checker = load_checker()
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[workspace\n")
    error = checker.build_report(invalid)
    assert error["status"] == "ERROR"
    assert [item["code"] for item in error["findings"]] == ["MANIFEST_INVALID"]

    missing_manifest = checker.build_report(tmp_path / "missing.toml")
    assert missing_manifest["status"] == "ERROR"
    assert [item["code"] for item in missing_manifest["findings"]] == [
        "MANIFEST_MISSING"
    ]

    valid_root = tmp_path / "valid"
    runtime = valid_root / "runtime view"
    missing = runtime / "repo" / "missing"
    manifest = write_manifest(valid_root, {"missing": missing})
    blocked = checker.build_report(manifest)
    assert blocked["status"] == "BLOCKED"
    assert "REPOSITORY_PATH_MISSING" in {
        item["code"] for item in blocked["findings"]
    }


def test_unregistered_runtime_directories_are_not_scanned(tmp_path):
    checker = load_checker()
    runtime = tmp_path / "runtime view"
    repo = init_repo(runtime / "repo" / "sample")
    ignored_area = runtime / "other worktrees" / "nested" / ".venv"
    ignored_area.mkdir(parents=True)
    (ignored_area / "cache.bin").write_text("cache\n")
    manifest = write_manifest(tmp_path, {"sample": repo})

    report = checker.build_report(manifest)

    assert "other worktrees" not in json.dumps(report)
    assert report["workspace"]["scanned_repositories"] == ["sample"]


def test_cli_human_and_json_have_same_status_and_findings(tmp_path):
    runtime = tmp_path / "runtime view"
    repo = init_repo(runtime / "repo" / "sample")
    manifest = write_manifest(tmp_path, {"sample": repo})
    (repo / "dirty.txt").write_text("dirty\n")

    human = run(sys.executable, str(CHECKER), "--manifest", str(manifest), check=False)
    machine = run(
        sys.executable,
        str(CHECKER),
        "--manifest",
        str(manifest),
        "--json",
        check=False,
    )
    report = json.loads(machine.stdout)

    assert human.returncode == machine.returncode == 1
    assert f"status={report['status']}" in human.stdout
    for finding in report["findings"]:
        assert finding["code"] in human.stdout


def test_cli_exit_codes_are_derived_from_structured_status(tmp_path):
    pass_root = tmp_path / "pass"
    pass_runtime = pass_root / "runtime view"
    pass_repo = init_repo(pass_runtime / "repo" / "sample")
    remote = tmp_path / "pass-remote.git"
    run("git", "init", "--bare", "-q", str(remote))
    git(pass_repo, "remote", "add", "origin", str(remote))
    git(pass_repo, "push", "-qu", "origin", "HEAD")
    pass_manifest = write_manifest(pass_root, {"sample": pass_repo})

    passed = run(
        sys.executable,
        str(CHECKER),
        "--manifest",
        str(pass_manifest),
        "--json",
        check=False,
    )
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["status"] == "PASS"

    (pass_repo / "untracked.txt").write_text("dirty\n")
    warned = run(
        sys.executable,
        str(CHECKER),
        "--manifest",
        str(pass_manifest),
        "--json",
        check=False,
    )
    assert warned.returncode == 1
    assert json.loads(warned.stdout)["status"] == "WARN"

    blocked_root = tmp_path / "blocked"
    blocked_repo = blocked_root / "runtime view" / "repo" / "missing"
    blocked_manifest = write_manifest(blocked_root, {"missing": blocked_repo})
    blocked = run(
        sys.executable,
        str(CHECKER),
        "--manifest",
        str(blocked_manifest),
        "--json",
        check=False,
    )
    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["status"] == "BLOCKED"

    invalid = tmp_path / "invalid-cli.toml"
    invalid.write_text("[workspace\n")
    errored = run(
        sys.executable,
        str(CHECKER),
        "--manifest",
        str(invalid),
        "--json",
        check=False,
    )
    assert errored.returncode == 3
    assert json.loads(errored.stdout)["status"] == "ERROR"


def test_install_links_is_idempotent_and_never_overwrites(tmp_path):
    target = tmp_path / "target"
    target.mkdir()

    first = run(str(INSTALL_LINKS), "--target-root", str(target), check=False)
    second = run(str(INSTALL_LINKS), "--target-root", str(target), check=False)

    assert first.returncode == second.returncode == 0
    assert (target / "scripts").is_symlink()
    assert (target / "scripts").resolve() == (ROOT / "code-workspace" / "scripts").resolve()
    assert (target / "templates").is_symlink()
    assert (target / "templates").resolve() == (ROOT / "code-workspace" / "templates").resolve()

    blocked_target = tmp_path / "blocked"
    (blocked_target / "scripts").mkdir(parents=True)
    marker = blocked_target / "scripts" / "keep.txt"
    marker.write_text("keep\n")
    blocked = run(
        str(INSTALL_LINKS),
        "--target-root",
        str(blocked_target),
        check=False,
    )
    assert blocked.returncode == 2
    assert marker.read_text() == "keep\n"

    template_conflict = tmp_path / "template-conflict"
    (template_conflict / "templates").mkdir(parents=True)
    blocked_before_create = run(
        str(INSTALL_LINKS),
        "--target-root",
        str(template_conflict),
        check=False,
    )
    assert blocked_before_create.returncode == 2
    assert not (template_conflict / "scripts").exists()


def test_installed_preflight_resolves_implementation_through_symlink(tmp_path):
    runtime = tmp_path / "runtime view"
    repo = init_repo(runtime / "repo" / "sample")
    manifest = write_manifest(tmp_path, {"sample": repo})
    target = tmp_path / "installed view"

    installed = run(
        str(INSTALL_LINKS),
        "--target-root",
        str(target),
        check=False,
    )
    result = run(
        str(target / "scripts" / "preflight"),
        "--manifest",
        str(manifest),
        "--json",
        check=False,
    )

    assert installed.returncode == 0
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "WARN"
