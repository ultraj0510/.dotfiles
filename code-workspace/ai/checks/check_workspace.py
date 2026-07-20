#!/usr/bin/env python3
"""Manifest-scoped workspace preflight and legacy checker entrypoint."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


SCHEMA_VERSION = 1
EXIT_CODES = {"PASS": 0, "WARN": 1, "BLOCKED": 2, "ERROR": 3}
SEVERITY_ORDER = {"PASS": 0, "WARN": 1, "BLOCKED": 2, "ERROR": 3}
WORKSPACE_PATH_FIELDS = (
    "human_documentation",
    "default_task_dir",
    "default_plan_dir",
    "default_archive_dir",
    "default_lessons_file",
)


class GitCollectionError(RuntimeError):
    pass


class UsageError(RuntimeError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def make_finding(code, severity, subject, message, details=None):
    return {
        "code": code,
        "severity": severity,
        "subject": subject,
        "message": message,
        "details": details or {},
    }


def exit_code(status):
    return EXIT_CODES[status]


def run_git(repo_path, *args, allowed_returncodes=(0,)):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise GitCollectionError(str(exc)) from exc
    if result.returncode not in allowed_returncodes:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise GitCollectionError(f"git {' '.join(args)}: {detail}")
    return result


def command_exists(repo_path, command):
    if not command:
        return False
    executable = command[0]
    if "/" in executable:
        path = repo_path / executable
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(executable) is not None


def parse_status(output):
    staged = []
    unstaged = []
    untracked = []
    entries = output.split("\0")
    skip_next = False
    for entry in entries:
        if not entry:
            continue
        if skip_next:
            skip_next = False
            continue
        status = entry[:2]
        path = entry[3:]
        if status == "??":
            untracked.append(path)
            continue
        if status[0] not in {" ", "?"}:
            staged.append(path)
        if status[1] not in {" ", "?"}:
            unstaged.append(path)
        if "R" in status or "C" in status:
            skip_next = True
    return sorted(staged), sorted(unstaged), sorted(untracked)


def collect_repository(name, repo_path, verification):
    repo_path = Path(repo_path)
    base = {
        "name": name,
        "path": str(repo_path),
        "collection_status": "OK",
        "branch": None,
        "detached": False,
        "upstream": None,
        "ahead": None,
        "behind": None,
        "dirty": False,
        "staged": [],
        "unstaged": [],
        "untracked": [],
        "verification": {
            "test_command": verification.get("test_command", []),
            "test_command_exists": False,
            "verify_command": verification.get("verify_command", []),
            "verify_command_exists": False,
        },
    }
    if not repo_path.exists():
        base["collection_status"] = "MISSING"
        return base
    if not repo_path.is_dir():
        base["collection_status"] = "NOT_GIT"
        return base
    if not (repo_path / ".git").exists():
        base["collection_status"] = "NOT_GIT"
        return base

    try:
        inside = run_git(
            repo_path,
            "rev-parse",
            "--is-inside-work-tree",
        )
        if inside.stdout.strip() != "true":
            raise GitCollectionError("registered repository is not a Git work tree")
        top_level = Path(
            run_git(repo_path, "rev-parse", "--show-toplevel").stdout.strip()
        ).resolve()
        if top_level != repo_path.resolve():
            base["collection_status"] = "NOT_GIT"
            return base

        branch = run_git(
            repo_path,
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            allowed_returncodes=(0, 1),
        )
        if branch.returncode == 0:
            base["branch"] = branch.stdout.strip()
        else:
            base["detached"] = True

        upstream = run_git(
            repo_path,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
            allowed_returncodes=(0, 128),
        )
        if upstream.returncode == 0:
            base["upstream"] = upstream.stdout.strip()
            counts = run_git(
                repo_path,
                "rev-list",
                "--left-right",
                "--count",
                "HEAD...@{upstream}",
            ).stdout.split()
            base["ahead"], base["behind"] = map(int, counts)

        status = run_git(
            repo_path,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=normal",
        )
        staged, unstaged, untracked = parse_status(status.stdout)
        base["staged"] = staged
        base["unstaged"] = unstaged
        base["untracked"] = untracked
        base["dirty"] = bool(staged or unstaged or untracked)
        base["verification"]["test_command_exists"] = command_exists(
            repo_path, base["verification"]["test_command"]
        )
        base["verification"]["verify_command_exists"] = command_exists(
            repo_path, base["verification"]["verify_command"]
        )
    except GitCollectionError as exc:
        base["collection_status"] = "ERROR"
        base["collection_error"] = str(exc)
    return base


def workspace_registered_paths(data):
    workspace = data["workspace"]
    paths = [workspace[field] for field in WORKSPACE_PATH_FIELDS]
    for section in ("tools", "runtime", "references", "generated"):
        paths.extend(data.get(section, {}).values())
    return paths


def collect_workspace(data, manifest_path):
    workspace = data["workspace"]
    runtime_view = Path(workspace["runtime_view"])
    source_repository = Path(workspace["source_repository"])
    missing_paths = [
        relative
        for relative in workspace_registered_paths(data)
        if not (runtime_view / relative).exists()
    ]
    runtime_manifest = runtime_view / "workspace.toml"
    expected_manifest = source_repository / "code-workspace" / "workspace.toml"
    source_link_valid = (
        runtime_manifest.is_symlink()
        and runtime_manifest.resolve() == expected_manifest.resolve()
    )
    return {
        "manifest": str(Path(manifest_path)),
        "manifest_valid": True,
        "runtime_view": str(runtime_view),
        "source_repository": str(source_repository),
        "source_repository_exists": source_repository.is_dir(),
        "missing_paths": sorted(missing_paths),
        "source_link_valid": source_link_valid,
        "scanned_repositories": [],
    }


def classify_artifact(repository, path):
    parts = Path(path).parts
    if parts and parts[0] == "outputs":
        return {
            "repository": repository,
            "kind": "generated_output",
            "path": path,
            "rule": "untracked path under outputs/",
        }
    if parts and parts[0] == "logs":
        return {
            "repository": repository,
            "kind": "log",
            "path": path,
            "rule": "untracked path under logs/",
        }
    if "__pycache__" in parts or ".pytest_cache" in parts:
        return {
            "repository": repository,
            "kind": "cache",
            "path": path,
            "rule": "untracked cache path",
        }
    return None


def evaluate_report(workspace, repositories, initial_findings=None):
    findings = list(initial_findings or [])
    suspicious = []

    for relative in workspace.get("missing_paths", []):
        findings.append(
            make_finding(
                "WORKSPACE_PATH_MISSING",
                "BLOCKED",
                "workspace",
                "Manifest-registered workspace path is missing",
                {"path": relative},
            )
        )
    if workspace.get("source_link_valid") is False:
        findings.append(
            make_finding(
                "WORKSPACE_SOURCE_LINK_INVALID",
                "BLOCKED",
                "workspace",
                "Runtime manifest does not point to the declared source repository",
                {"manifest": workspace.get("manifest")},
            )
        )
    if workspace.get("source_repository_exists") is False:
        findings.append(
            make_finding(
                "WORKSPACE_SOURCE_REPOSITORY_MISSING",
                "BLOCKED",
                "workspace",
                "Declared source repository does not exist",
                {"path": workspace.get("source_repository")},
            )
        )

    for repo in repositories:
        name = repo["name"]
        collection_status = repo["collection_status"]
        if collection_status == "MISSING":
            findings.append(
                make_finding(
                    "REPOSITORY_PATH_MISSING",
                    "BLOCKED",
                    name,
                    "Manifest-registered repository path is missing",
                    {"path": repo["path"]},
                )
            )
            continue
        if collection_status == "NOT_GIT":
            findings.append(
                make_finding(
                    "REPOSITORY_NOT_GIT",
                    "BLOCKED",
                    name,
                    "Manifest-registered repository path is not a Git work tree",
                    {"path": repo["path"]},
                )
            )
            continue
        if collection_status == "ERROR":
            findings.append(
                make_finding(
                    "GIT_COMMAND_FAILED",
                    "ERROR",
                    name,
                    "Git facts could not be collected reliably",
                    {"error": repo.get("collection_error", "unknown error")},
                )
            )
            continue

        if repo["detached"]:
            findings.append(
                make_finding(
                    "REPOSITORY_DETACHED_HEAD",
                    "WARN",
                    name,
                    "Repository is on a detached HEAD",
                )
            )
        if repo["upstream"] is None:
            findings.append(
                make_finding(
                    "REPOSITORY_NO_UPSTREAM",
                    "WARN",
                    name,
                    "Repository has no upstream",
                )
            )
        else:
            if repo["ahead"]:
                findings.append(
                    make_finding(
                        "REPOSITORY_AHEAD_UPSTREAM",
                        "WARN",
                        name,
                        "Repository is ahead of its upstream",
                        {"ahead": repo["ahead"]},
                    )
                )
            if repo["behind"]:
                findings.append(
                    make_finding(
                        "REPOSITORY_BEHIND_UPSTREAM",
                        "WARN",
                        name,
                        "Repository is behind its upstream",
                        {"behind": repo["behind"]},
                    )
                )
        if repo["dirty"]:
            findings.append(
                make_finding(
                    "REPOSITORY_DIRTY",
                    "WARN",
                    name,
                    "Repository has staged, unstaged, or untracked changes",
                    {
                        "staged": len(repo["staged"]),
                        "unstaged": len(repo["unstaged"]),
                        "untracked": len(repo["untracked"]),
                    },
                )
            )
        verification = repo["verification"]
        if not verification["test_command_exists"]:
            findings.append(
                make_finding(
                    "TEST_COMMAND_UNAVAILABLE",
                    "WARN",
                    name,
                    "Configured test command is unavailable",
                    {"command": verification["test_command"]},
                )
            )
        if not verification["verify_command_exists"]:
            findings.append(
                make_finding(
                    "VERIFY_COMMAND_UNAVAILABLE",
                    "WARN",
                    name,
                    "Configured verification command is unavailable",
                    {"command": verification["verify_command"]},
                )
            )
        for path in repo["untracked"]:
            artifact = classify_artifact(name, path)
            if artifact:
                suspicious.append(artifact)
                findings.append(
                    make_finding(
                        "SUSPICIOUS_UNTRACKED_ARTIFACT",
                        "WARN",
                        name,
                        "Untracked generated artifact matches a hygiene rule",
                        artifact,
                    )
                )

    status = "PASS"
    for finding in findings:
        if SEVERITY_ORDER[finding["severity"]] > SEVERITY_ORDER[status]:
            status = finding["severity"]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "workspace": workspace,
        "repositories": repositories,
        "artifacts": {"suspicious_untracked": suspicious},
        "findings": findings,
    }


def error_report(manifest_path, code, message, details=None):
    workspace = {
        "manifest": str(Path(manifest_path)),
        "manifest_valid": False,
        "runtime_view": None,
        "source_repository": None,
        "source_repository_exists": None,
        "missing_paths": [],
        "source_link_valid": None,
        "scanned_repositories": [],
    }
    return evaluate_report(
        workspace,
        [],
        [make_finding(code, "ERROR", "preflight", message, details)],
    )


def validate_manifest(data):
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a table")
    for section in ("workspace", "repos", "verification"):
        if not isinstance(data.get(section), dict):
            raise ValueError(f"missing or invalid [{section}] table")
    workspace = data["workspace"]
    for field in ("root", "runtime_view", "source_repository", *WORKSPACE_PATH_FIELDS):
        if not isinstance(workspace.get(field), str) or not workspace[field]:
            raise ValueError(f"workspace.{field} must be a non-empty string")
    if workspace["root"] != workspace["runtime_view"]:
        raise ValueError("workspace.root must equal workspace.runtime_view")
    for section in ("tools", "runtime", "references", "generated"):
        values = data.get(section, {})
        if not isinstance(values, dict) or not all(
            isinstance(value, str) and value for value in values.values()
        ):
            raise ValueError(f"[{section}] paths must be non-empty strings")
    if not all(
        isinstance(value, str) and value for value in data["repos"].values()
    ):
        raise ValueError("[repos] paths must be non-empty strings")
    if set(data["repos"]) != set(data["verification"]):
        raise ValueError("[verification] keys must match [repos] keys")
    for name, commands in data["verification"].items():
        if set(commands) != {"test_command", "verify_command"}:
            raise ValueError(f"verification.{name} must define test_command and verify_command")
        if not all(isinstance(value, list) for value in commands.values()):
            raise ValueError(f"verification.{name} commands must be arrays")
        if not all(
            isinstance(part, str)
            for command in commands.values()
            for part in command
        ):
            raise ValueError(f"verification.{name} command parts must be strings")


def build_report(manifest_path, repo_path=None):
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return error_report(
            manifest_path,
            "MANIFEST_MISSING",
            "Workspace manifest does not exist",
        )
    try:
        data = tomllib.loads(manifest_path.read_text())
        validate_manifest(data)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        return error_report(
            manifest_path,
            "MANIFEST_INVALID",
            "Workspace manifest cannot be parsed or validated",
            {"error": str(exc)},
        )

    workspace = collect_workspace(data, manifest_path)
    runtime_view = Path(data["workspace"]["runtime_view"])
    selected = list(data["repos"])
    initial_findings = []
    if repo_path is not None:
        requested = Path(repo_path).resolve()
        selected = [
            name
            for name, relative in data["repos"].items()
            if (runtime_view / relative).resolve() == requested
        ]
        if not selected:
            initial_findings.append(
                make_finding(
                    "REPOSITORY_NOT_REGISTERED",
                    "BLOCKED",
                    str(repo_path),
                    "Requested repository is not registered in the manifest",
                )
            )

    repositories = [
        collect_repository(
            name,
            runtime_view / data["repos"][name],
            data["verification"][name],
        )
        for name in selected
    ]
    workspace["scanned_repositories"] = selected
    return evaluate_report(workspace, repositories, initial_findings)


def render_json(report):
    return json.dumps(report, ensure_ascii=False, indent=2)


def render_human(report):
    workspace = report["workspace"]
    lines = [
        "[preflight]",
        f"schema_version={report['schema_version']}",
        f"status={report['status']}",
        "[workspace]",
        f"manifest={workspace.get('manifest')}",
        f"manifest_valid={str(workspace.get('manifest_valid')).lower()}",
        f"runtime_view={workspace.get('runtime_view')}",
    ]
    for repo in report["repositories"]:
        lines.extend(
            [
                f"[repository {repo['name']}]",
                f"path={repo['path']}",
                f"branch={repo['branch']}",
                f"upstream={repo['upstream']}",
                f"ahead={repo['ahead']}",
                f"behind={repo['behind']}",
                f"dirty={str(repo['dirty']).lower()}",
                f"staged={len(repo['staged'])}",
                f"unstaged={len(repo['unstaged'])}",
                f"untracked={len(repo['untracked'])}",
            ]
        )
    lines.extend(
        [
            "[artifacts]",
            f"suspicious_untracked={len(report['artifacts']['suspicious_untracked'])}",
            "[findings]",
        ]
    )
    if not report["findings"]:
        lines.append("none")
    for finding in report["findings"]:
        lines.append(
            f"- {finding['severity']} {finding['code']} subject={finding['subject']}: "
            f"{finding['message']} details={json.dumps(finding['details'], ensure_ascii=False)}"
        )
    return "\n".join(lines) + "\n"


def parse_args(argv):
    parser = Parser(description="Manifest-scoped workspace preflight")
    source_workspace = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(os.environ.get("CODE_WORKSPACE_ROOT", str(source_workspace)))
        / "workspace.toml",
    )
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args(argv)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    try:
        args = parse_args(argv)
        report = build_report(args.manifest, args.repo)
        output = render_json(report) + "\n" if args.as_json else render_human(report)
    except UsageError as exc:
        report = error_report(
            Path("<arguments>"),
            "PREFLIGHT_ARGUMENT_ERROR",
            "Invalid preflight arguments",
            {"error": str(exc)},
        )
        output = render_json(report) + "\n" if as_json else render_human(report)
    except Exception as exc:
        report = error_report(
            Path("<internal>"),
            "PREFLIGHT_INTERNAL_ERROR",
            "Preflight failed before reliable collection completed",
            {"error": str(exc)},
        )
        output = render_json(report) + "\n" if as_json else render_human(report)
    sys.stdout.write(output)
    return exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
