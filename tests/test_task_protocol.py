import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "code-workspace" / "ai" / "governance" / "task_protocol.py"
TASKCTL = ROOT / "code-workspace" / "scripts" / "taskctl"
INSTALL_LINKS = ROOT / "code-workspace" / "scripts" / "install-links"

ALL_TRIGGERS = {
    "local_change": False,
    "reversible": False,
    "external_side_effect": False,
    "schema_or_contract_change": False,
    "cross_module_change": False,
    "public_behavior_change": False,
    "persisted_data_change": False,
    "dependency_change": False,
    "money": False,
    "production": False,
    "security": False,
    "credentials": False,
    "destructive_migration": False,
    "irreversible_external_action": False,
}


def load_protocol():
    spec = importlib.util.spec_from_file_location("task_protocol", PROTOCOL)
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


def init_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "taskctl@example.invalid")
    git(path, "config", "user.name", "Taskctl Test")
    (path / "tracked.txt").write_text("base\n")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-qm", "base")
    return path


def make_preflight(path, status="WARN", schema_version=1, valid_json=True, delay=0):
    exit_codes = {"PASS": 0, "WARN": 1, "BLOCKED": 2, "ERROR": 3}
    if valid_json:
        payload = json.dumps(
            {
                "schema_version": schema_version,
                "status": status,
                "workspace": {},
                "repositories": [],
                "artifacts": {},
                "findings": [],
            }
        )
        body = (
            f"import time\ntime.sleep({delay!r})\n"
            f"print({payload!r})\nraise SystemExit({exit_codes[status]})\n"
        )
    else:
        body = "print('not-json')\nraise SystemExit(0)\n"
    path.write_text(f"#!/usr/bin/env python3\n{body}")
    path.chmod(0o755)
    return path


def task_text(
    repo,
    *,
    task_id="task-1",
    level="L1",
    acceptance=None,
    overrides=None,
    status=None,
    risk_level=None,
):
    acceptance = acceptance or [
        {
            "id": "accept-1",
            "description": "command succeeds",
            "command": [sys.executable, "-c", "print('ok')"],
        }
    ]
    triggers = dict(ALL_TRIGGERS)
    triggers[{"L1": "local_change", "L2": "public_behavior_change", "L3": "money"}[level]] = True
    triggers.update(overrides or {})
    acceptance_toml = "[" + ", ".join(
        "{ id = %s, description = %s, command = %s }"
        % (
            json.dumps(item["id"]),
            json.dumps(item["description"]),
            json.dumps(item["command"]),
        )
        for item in acceptance
    ) + "]"
    lines = [
        "+++",
        "schema_version = 1",
        f"id = {json.dumps(task_id)}",
        f"repo = {json.dumps(str(repo))}",
        'allowed_paths = ["src/", "tests/"]',
        f"minimum_level = {json.dumps('L1')}",
        'implementer = "implementer-a"',
        f"acceptance = {acceptance_toml}",
    ]
    if status is not None:
        lines.append(f"status = {json.dumps(status)}")
    if risk_level is not None:
        lines.append(f"risk_level = {json.dumps(risk_level)}")
    lines.append("")
    lines.append("[risk]")
    lines.extend(f"{name} = {str(value).lower()}" for name, value in triggers.items())
    lines.extend(["+++", "", "# Goal", "", "Test task.", ""])
    return "\n".join(lines)


def write_task(tmp_path, repo, **kwargs):
    task = tmp_path / f"{kwargs.get('task_id', 'task-1')}.md"
    task.write_text(task_text(repo, **kwargs))
    return task


def cli(preflight, workspace, *args):
    return run(
        sys.executable,
        str(PROTOCOL),
        "--workspace-root",
        str(workspace),
        "--preflight",
        str(preflight),
        *map(str, args),
        check=False,
    )


def start(preflight, workspace, task):
    return cli(preflight, workspace, "start", task, "--json")


def run_acceptance(preflight, workspace, task, evidence, kind, command, archive=None):
    args = [
        "run",
        task,
        "--evidence",
        evidence,
        "--kind",
        kind,
        "--acceptance",
        "accept-1",
    ]
    if archive is not None:
        args.extend(["--archive-dir", archive])
    args.extend(["--", *command])
    return cli(preflight, workspace, *args)


@pytest.mark.parametrize(
    ("triggers", "expected"),
    [
        (["local_change"], "L1"),
        (["public_behavior_change"], "L2"),
        (["money"], "L3"),
        (["local_change", "dependency_change"], "L2"),
        (["local_change", "security"], "L3"),
        (["public_behavior_change", "credentials"], "L3"),
    ],
)
def test_risk_classification_uses_highest_trigger(triggers, expected):
    protocol = load_protocol()
    assert protocol.classify_risk(triggers, "L1")["level"] == expected


def test_risk_classification_is_order_and_duplicate_invariant():
    protocol = load_protocol()
    first = protocol.classify_risk(
        ["local_change", "security", "local_change"], "L1"
    )
    second = protocol.classify_risk(["security", "local_change"], "L1")
    assert first == second
    assert first["matched_triggers"] == ["local_change", "security"]


def test_minimum_level_is_only_a_risk_floor():
    protocol = load_protocol()
    assert protocol.classify_risk(["local_change"], "L2")["level"] == "L2"
    assert protocol.classify_risk(["money"], "L1")["level"] == "L3"


@pytest.mark.parametrize("triggers", [["unknown"], [], None])
def test_unknown_missing_or_damaged_triggers_are_rejected(triggers):
    protocol = load_protocol()
    with pytest.raises(protocol.TaskSchemaError):
        protocol.classify_risk(triggers, "L1")


def test_task_schema_rejects_missing_trigger_duplicate_acceptance_and_path_escape(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)

    text = task.read_text().replace("local_change = true\n", "")
    task.write_text(text)
    with pytest.raises(protocol.TaskSchemaError):
        protocol.load_task(task, tmp_path)

    task.write_text(task_text(repo, task_id="../../escape"))
    with pytest.raises(protocol.TaskSchemaError):
        protocol.load_task(task, tmp_path)

    duplicate = [
        {"id": "same", "description": "a", "command": ["true"]},
        {"id": "same", "description": "b", "command": ["true"]},
    ]
    task.write_text(task_text(repo, acceptance=duplicate))
    with pytest.raises(protocol.TaskSchemaError):
        protocol.load_task(task, tmp_path)

    task.write_text(task_text(repo).replace('allowed_paths = ["src/", "tests/"]', 'allowed_paths = ["../"]'))
    with pytest.raises(protocol.TaskSchemaError):
        protocol.load_task(task, tmp_path)

    task.write_text(task_text(repo).replace('allowed_paths = ["src/", "tests/"]', 'allowed_paths = "src/"'))
    with pytest.raises(protocol.TaskSchemaError):
        protocol.load_task(task, tmp_path)


def test_task_definition_must_be_outside_target_repository(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    task = write_task(repo, repo)

    with pytest.raises(protocol.TaskSchemaError):
        protocol.load_task(task, tmp_path)


def test_empty_acceptance_command_is_not_vacuous_success(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    acceptance = [{"id": "accept-1", "description": "empty", "command": []}]
    task = write_task(tmp_path, repo, acceptance=acceptance)
    with pytest.raises(protocol.TaskSchemaError):
        protocol.load_task(task, tmp_path)


@pytest.mark.parametrize(
    ("preflight_status", "expected_result", "expected_exit"),
    [("WARN", "READY", 0), ("BLOCKED", "BLOCKED", 2)],
)
def test_start_consumes_valid_nonzero_preflight_reports(
    tmp_path, preflight_status, expected_result, expected_exit
):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    preflight = make_preflight(tmp_path / "preflight", preflight_status)

    result = start(preflight, tmp_path, task)
    report = json.loads(result.stdout)

    assert result.returncode == expected_exit
    assert report["preflight"]["status"] == preflight_status
    assert report["result"]["status"] == expected_result


@pytest.mark.parametrize(
    "preflight",
    [
        ("ERROR", 1, True),
        ("PASS", 99, True),
        ("PASS", 1, False),
    ],
)
def test_preflight_error_bad_schema_and_bad_json_are_interface_errors(tmp_path, preflight):
    status, schema, valid_json = preflight
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    executable = make_preflight(
        tmp_path / "preflight", status, schema_version=schema, valid_json=valid_json
    )

    result = start(executable, tmp_path, task)

    assert result.returncode == 3
    assert json.loads(result.stdout)["result"]["status"] == "ERROR"


def test_start_creates_integrity_checked_managed_state_and_never_complete(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, status="COMPLETE")
    preflight = make_preflight(tmp_path / "preflight")

    result = start(preflight, tmp_path, task)
    report = json.loads(result.stdout)
    state_path = protocol.state_path_for(task, "task-1")
    state = json.loads(state_path.read_text())
    registry = json.loads(protocol.registry_path_for(repo).read_text())

    assert result.returncode == 0
    assert report["result"]["status"] == "READY"
    assert state["task_id"] == "task-1"
    assert state["risk_floor"] == "L1"
    assert state["initial_workspace"]["repository_identity"] == str(repo.resolve())
    assert state["initial_workspace"]["head"] == git(repo, "rev-parse", "HEAD")
    assert state["initial_preflight"]["schema_version"] == 1
    assert state["initial_preflight"]["status"] == "WARN"
    assert state["integrity_sha256"] == protocol.managed_digest(state)
    assert registry["tasks"][str(repo.resolve())]["task-1"]["risk_floor"] == "L1"
    assert registry["integrity_sha256"] == protocol.managed_digest(registry)
    assert "COMPLETE" not in state.values()


def test_run_records_auditable_item_bound_to_current_workspace(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    command = [sys.executable, "-c", "print('ok')"]
    assert start(preflight, tmp_path, task).returncode == 0

    result = run_acceptance(
        preflight, tmp_path, task, evidence, "focused_test", command
    )
    payload = json.loads(evidence.read_text())
    item = payload["commands"][0]

    assert result.returncode == 0
    assert item["task_id"] == "task-1"
    assert item["acceptance_ids"] == ["accept-1"]
    assert item["argv"] == command
    assert item["cwd"] == str(repo.resolve())
    assert item["exit_code"] == 0
    assert len(item["stdout_sha256"]) == len(item["stderr_sha256"]) == 64
    assert item["workspace"]["repository_identity"] == str(repo.resolve())
    assert item["workspace"]["branch"] == git(repo, "branch", "--show-current")
    assert item["workspace"]["head"] == git(repo, "rev-parse", "HEAD")
    assert item["preflight"]["schema_version"] == 1


@pytest.mark.parametrize("location", ["evidence", "archive"])
def test_evidence_and_archive_must_be_outside_target_repository(tmp_path, location):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, level="L3" if location == "archive" else "L1")
    preflight = make_preflight(tmp_path / "preflight")
    evidence = repo / "evidence.json" if location == "evidence" else tmp_path / "evidence.json"
    archive = repo / "archive" if location == "archive" else None
    if archive is not None:
        archive.mkdir()
    start(preflight, tmp_path, task)

    result = run_acceptance(
        preflight,
        tmp_path,
        task,
        evidence,
        "full_test" if location == "archive" else "focused_test",
        [sys.executable, "-c", "print('ok')"],
        archive,
    )

    assert result.returncode == 3
    assert result.stdout.startswith("Result: ERROR\n")


@pytest.mark.parametrize(
    ("command", "expected_exit"),
    [
        ([sys.executable, "-c", "raise SystemExit(7)"], 7),
        (["/definitely/missing/taskctl-command"], 127),
        (["sh", "-c", "kill -TERM $$"], 143),
    ],
)
def test_failed_missing_and_interrupted_commands_cannot_complete(
    tmp_path, command, expected_exit
):
    repo = init_repo(tmp_path / "repo")
    acceptance = [{"id": "accept-1", "description": "fails", "command": command}]
    task = write_task(tmp_path, repo, acceptance=acceptance)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    start(preflight, tmp_path, task)

    run_result = run_acceptance(
        preflight, tmp_path, task, evidence, "focused_test", command
    )
    close_result = cli(
        preflight, tmp_path, "close", task, "--evidence", evidence, "--json"
    )

    assert run_result.returncode == expected_exit
    assert json.loads(close_result.stdout)["result"]["status"] != "COMPLETE"


def test_partial_acceptance_coverage_cannot_complete(tmp_path):
    repo = init_repo(tmp_path / "repo")
    command = [sys.executable, "-c", "print('ok')"]
    acceptance = [
        {"id": "accept-1", "description": "one", "command": command},
        {"id": "accept-2", "description": "two", "command": command},
    ]
    task = write_task(tmp_path, repo, acceptance=acceptance)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "focused_test", command)

    result = cli(preflight, tmp_path, "close", task, "--evidence", evidence, "--json")

    assert result.returncode == 1
    assert json.loads(result.stdout)["result"]["status"] == "PARTIAL"


@pytest.mark.parametrize("level", ["L1", "L2", "L3"])
def test_start_run_close_end_to_end_for_each_level(tmp_path, level):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, level=level)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight", "WARN")
    archive = tmp_path / "archive"
    archive.mkdir()
    command = [sys.executable, "-c", "print('ok')"]
    kind = {"L1": "focused_test", "L2": "regression_test", "L3": "full_test"}[level]

    assert start(preflight, tmp_path, task).returncode == 0
    run_result = run_acceptance(
        preflight,
        tmp_path,
        task,
        evidence,
        kind,
        command,
        archive if level == "L3" else None,
    )
    close_args = ["close", task, "--evidence", evidence, "--json"]
    if level == "L3":
        close_args.extend(
            [
                "--approval-ref",
                "approval:user:2026-07-20",
                "--reviewer",
                "reviewer-b",
                "--review-ref",
                "review:task-1:final",
            ]
        )
    close_result = cli(preflight, tmp_path, *close_args)
    report = json.loads(close_result.stdout)

    assert run_result.returncode == 0
    assert close_result.returncode == 0
    assert report["risk"]["level"] == level
    assert report["result"]["status"] == "COMPLETE"


@pytest.mark.parametrize("missing_gate", ["approval", "review", "archive"])
def test_l3_requires_each_independent_gate(tmp_path, missing_gate):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, level="L3")
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    archive = tmp_path / "archive"
    if missing_gate != "archive":
        archive.mkdir()
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(
        preflight,
        tmp_path,
        task,
        evidence,
        "full_test",
        command,
        archive if missing_gate != "archive" else None,
    )
    args = ["close", task, "--evidence", evidence, "--json"]
    if missing_gate != "approval":
        args.extend(["--approval-ref", "approval:user:2026-07-20"])
    if missing_gate != "review":
        args.extend(
            ["--reviewer", "reviewer-b", "--review-ref", "review:task-1:final"]
        )

    result = cli(preflight, tmp_path, *args)
    report = json.loads(result.stdout)

    assert result.returncode == 2
    assert report["result"]["status"] == "BLOCKED"
    assert f"L3_{missing_gate.upper()}_MISSING" in report["result"]["reasons"]


def test_l3_review_must_be_independent_and_match_current_fingerprint(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, level="L3")
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    archive = tmp_path / "archive"
    archive.mkdir()
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "full_test", command, archive)

    same_identity = cli(
        preflight,
        tmp_path,
        "close",
        task,
        "--evidence",
        evidence,
        "--approval-ref",
        "approval:user:2026-07-20",
        "--reviewer",
        "implementer-a",
        "--review-ref",
        "review:task-1:final",
        "--json",
    )
    assert json.loads(same_identity.stdout)["result"]["status"] == "BLOCKED"

    (repo / "src").mkdir()
    (repo / "src" / "changed.py").write_text("changed\n")
    stale = cli(
        preflight,
        tmp_path,
        "close",
        task,
        "--evidence",
        evidence,
        "--approval-ref",
        "approval:user:2026-07-20",
        "--reviewer",
        "reviewer-b",
        "--review-ref",
        "review:task-1:final",
        "--json",
    )
    assert json.loads(stale.stdout)["result"]["status"] == "BLOCKED"


def test_l3_review_record_becomes_stale_after_implementation_changes(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, level="L3")
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    archive = tmp_path / "archive"
    archive.mkdir()
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "full_test", command, archive)
    completed = cli(
        preflight,
        tmp_path,
        "close",
        task,
        "--evidence",
        evidence,
        "--approval-ref",
        "approval:user:2026-07-20",
        "--reviewer",
        "reviewer-b",
        "--review-ref",
        "review:task-1:final",
        "--json",
    )
    assert json.loads(completed.stdout)["result"]["status"] == "COMPLETE"

    (repo / "src").mkdir()
    (repo / "src" / "after-review.py").write_text("changed\n")
    stale = cli(
        preflight,
        tmp_path,
        "close",
        task,
        "--evidence",
        evidence,
        "--json",
    )
    reasons = json.loads(stale.stdout)["result"]["reasons"]

    assert stale.returncode == 2
    assert "L3_REVIEW_MISSING" in reasons


@pytest.mark.parametrize(
    "mutation",
    ["head", "staged", "unstaged", "untracked", "branch", "task", "task_id", "repo"],
)
def test_evidence_identity_changes_make_old_evidence_invalid(tmp_path, mutation):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "focused_test", command)

    if mutation == "head":
        (repo / "head.txt").write_text("head\n")
        git(repo, "add", "head.txt")
        git(repo, "commit", "-qm", "head")
    elif mutation == "staged":
        (repo / "src").mkdir()
        (repo / "src" / "staged.py").write_text("staged\n")
        git(repo, "add", "src/staged.py")
    elif mutation == "unstaged":
        (repo / "tracked.txt").write_text("changed\n")
    elif mutation == "untracked":
        (repo / "src").mkdir()
        (repo / "src" / "new.py").write_text("new\n")
    elif mutation == "branch":
        git(repo, "checkout", "-qb", "other")
    elif mutation == "task":
        task.write_text(task.read_text().replace("print('ok')", "print('changed')"))
    elif mutation == "task_id":
        task.write_text(task.read_text().replace('id = "task-1"', 'id = "task-2"'))
    elif mutation == "repo":
        other = init_repo(tmp_path / "other")
        task.write_text(task.read_text().replace(str(repo), str(other)))

    result = cli(preflight, tmp_path, "close", task, "--evidence", evidence, "--json")

    assert result.returncode == 2
    assert json.loads(result.stdout)["result"]["status"] == "BLOCKED"


def test_fresh_acceptance_supersedes_stale_history(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "focused_test", command)
    (repo / "src").mkdir()
    (repo / "src" / "new.py").write_text("new\n")

    rerun = run_acceptance(
        preflight, tmp_path, task, evidence, "focused_test", command
    )
    result = cli(
        preflight, tmp_path, "close", task, "--evidence", evidence, "--json"
    )

    assert rerun.returncode == 0
    assert result.returncode == 0
    assert json.loads(result.stdout)["result"]["status"] == "COMPLETE"


def test_manual_complete_and_risk_downgrade_do_not_bypass_close(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(
        tmp_path, repo, level="L3", status="COMPLETE", risk_level="L1"
    )
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    start(preflight, tmp_path, task)
    task.write_text(task_text(repo, level="L1", status="COMPLETE", risk_level="L1"))

    result = cli(preflight, tmp_path, "close", task, "--evidence", evidence, "--json")
    report = json.loads(result.stdout)

    assert result.returncode == 2
    assert report["risk"]["level"] == "L3"
    assert report["result"]["status"] == "BLOCKED"


def test_registered_task_cannot_restart_after_managed_state_is_deleted(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, level="L3")
    preflight = make_preflight(tmp_path / "preflight")
    assert start(preflight, tmp_path, task).returncode == 0
    protocol.state_path_for(task, "task-1").unlink()
    task.write_text(task_text(repo, level="L1"))

    result = start(preflight, tmp_path, task)
    report = json.loads(result.stdout)

    assert result.returncode == 2
    assert report["result"]["status"] == "BLOCKED"
    assert "MANAGED_STATE_MISSING" in report["result"]["reasons"]
    assert not protocol.state_path_for(task, "task-1").exists()


def test_registered_task_cannot_downgrade_by_moving_definition(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    first_dir = tmp_path / "tasks-a"
    second_dir = tmp_path / "tasks-b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = write_task(first_dir, repo, level="L3")
    second = write_task(second_dir, repo, level="L1")
    preflight = make_preflight(tmp_path / "preflight")
    assert start(preflight, tmp_path, first).returncode == 0

    result = start(preflight, second_dir, second)
    report = json.loads(result.stdout)

    assert result.returncode == 2
    assert report["risk"]["level"] == "L3"
    assert "MANAGED_STATE_MISSING" in report["result"]["reasons"]
    assert not protocol.state_path_for(second, "task-1").exists()


@pytest.mark.parametrize("mutation", ["modify", "delete", "empty"])
def test_modified_deleted_or_empty_evidence_is_rejected(tmp_path, mutation):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "focused_test", command)
    if mutation == "modify":
        payload = json.loads(evidence.read_text())
        payload["commands"][0]["exit_code"] = 0
        payload["commands"][0]["stdout_sha256"] = "0" * 64
        evidence.write_text(json.dumps(payload))
    elif mutation == "delete":
        evidence.unlink()
    else:
        evidence.write_text("")

    result = cli(preflight, tmp_path, "close", task, "--evidence", evidence, "--json")
    assert result.returncode == 2
    assert json.loads(result.stdout)["result"]["status"] == "BLOCKED"


def test_l3_deleted_archive_invalidates_completion(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, level="L3")
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    archive = tmp_path / "archive"
    archive.mkdir()
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "full_test", command, archive)
    payload = json.loads(evidence.read_text())
    Path(payload["commands"][0]["archive"]["stdout_path"]).unlink()

    result = cli(
        preflight,
        tmp_path,
        "close",
        task,
        "--evidence",
        evidence,
        "--approval-ref",
        "approval:user:2026-07-20",
        "--reviewer",
        "reviewer-b",
        "--review-ref",
        "review:task-1:final",
        "--json",
    )

    assert result.returncode == 2
    assert "L3_ARCHIVE_MISSING" in json.loads(result.stdout)["result"]["reasons"]


def test_close_rejects_damaged_preflight_interface(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    evidence = tmp_path / "evidence.json"
    valid = make_preflight(tmp_path / "valid")
    broken = make_preflight(tmp_path / "broken", valid_json=False)
    command = [sys.executable, "-c", "print('ok')"]
    start(valid, tmp_path, task)
    run_acceptance(valid, tmp_path, task, evidence, "focused_test", command)

    result = cli(broken, tmp_path, "close", task, "--evidence", evidence, "--json")

    assert result.returncode == 3
    assert json.loads(result.stdout)["result"]["status"] == "ERROR"


def test_blocked_preflight_never_closes_complete(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    evidence = tmp_path / "evidence.json"
    warn = make_preflight(tmp_path / "warn", "WARN")
    blocked = make_preflight(tmp_path / "blocked", "BLOCKED")
    command = [sys.executable, "-c", "print('ok')"]
    start(warn, tmp_path, task)
    run_acceptance(warn, tmp_path, task, evidence, "focused_test", command)

    result = cli(blocked, tmp_path, "close", task, "--evidence", evidence, "--json")

    assert result.returncode == 2
    assert json.loads(result.stdout)["result"]["status"] == "BLOCKED"


def test_changed_path_outside_allowed_scope_blocks_close(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    (repo / "outside.txt").write_text("outside\n")
    run_acceptance(preflight, tmp_path, task, evidence, "focused_test", command)

    result = cli(preflight, tmp_path, "close", task, "--evidence", evidence, "--json")

    assert result.returncode == 2
    assert "CHANGED_PATH_OUTSIDE_SCOPE" in json.loads(result.stdout)["result"]["reasons"]


def test_managed_state_uses_atomic_replace_and_detects_manual_edit(tmp_path, monkeypatch):
    protocol = load_protocol()
    target = tmp_path / "state.json"
    calls = []
    real_replace = os.replace

    def recording_replace(source, destination):
        calls.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(protocol.os, "replace", recording_replace)
    protocol.atomic_write_json(target, {"value": 1})
    assert calls and calls[0][1] == target

    state = {"schema_version": 1, "task_id": "task-1"}
    state["integrity_sha256"] = protocol.managed_digest(state)
    target.write_text(json.dumps(state))
    assert protocol.load_managed_state(target)["task_id"] == "task-1"
    state["task_id"] = "tampered"
    target.write_text(json.dumps(state))
    with pytest.raises(protocol.ManagedStateError):
        protocol.load_managed_state(target)


def test_twenty_concurrent_starts_do_not_lose_registry_entries(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    preflight = make_preflight(tmp_path / "preflight", delay=0.2)
    tasks = [write_task(tmp_path, repo, task_id=f"task-{index}") for index in range(20)]
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                str(PROTOCOL),
                "--workspace-root",
                str(tmp_path),
                "--preflight",
                str(preflight),
                "start",
                str(task),
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for task in tasks
    ]
    results = [process.communicate(timeout=30) for process in processes]
    registry = protocol.load_registry(protocol.registry_path_for(repo))

    assert all(process.returncode == 0 for process in processes), results
    assert set(registry["tasks"][str(repo.resolve())]) == {
        f"task-{index}" for index in range(20)
    }


def test_concurrent_same_id_start_has_one_registration(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    preflight = make_preflight(tmp_path / "preflight", delay=0.2)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    tasks = [write_task(first_dir, repo), write_task(second_dir, repo)]
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                str(PROTOCOL),
                "--workspace-root",
                str(tmp_path),
                "--preflight",
                str(preflight),
                "start",
                str(task),
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for task in tasks
    ]
    results = [process.communicate(timeout=30) for process in processes]
    registry = protocol.load_registry(protocol.registry_path_for(repo))

    assert sorted(process.returncode for process in processes) == [0, 2], results
    assert list(registry["tasks"][str(repo.resolve())]) == ["task-1"]
    assert sum(protocol.state_path_for(task, "task-1").exists() for task in tasks) == 1


def test_concurrent_runs_preserve_both_evidence_records(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    command = [sys.executable, "-c", "import time; time.sleep(0.2)"]
    acceptance = [
        {"id": "accept-1", "description": "one", "command": command},
        {"id": "accept-2", "description": "two", "command": command},
    ]
    task = write_task(tmp_path, repo, acceptance=acceptance)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    assert start(preflight, tmp_path, task).returncode == 0
    base = [
        sys.executable,
        str(PROTOCOL),
        "--workspace-root",
        str(tmp_path),
        "--preflight",
        str(preflight),
        "run",
        str(task),
        "--evidence",
        str(evidence),
        "--kind",
        "focused_test",
    ]
    processes = [
        subprocess.Popen(
            [*base, "--acceptance", identifier, "--", *command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for identifier in ("accept-1", "accept-2")
    ]
    results = [process.communicate(timeout=30) for process in processes]
    payload = json.loads(evidence.read_text())
    state = protocol.load_managed_state(protocol.state_path_for(task, "task-1"))

    assert all(process.returncode == 0 for process in processes), results
    assert [record["id"] for record in payload["commands"]] == ["command:0", "command:1"]
    assert {tuple(record["acceptance_ids"]) for record in payload["commands"]} == {
        ("accept-1",),
        ("accept-2",),
    }
    assert state["evidence_sha256"] == protocol.file_sha256(evidence)


def test_concurrent_l3_close_preserves_complementary_gates(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo, level="L3")
    evidence = tmp_path / "evidence.json"
    archive = tmp_path / "archive"
    archive.mkdir()
    preflight = make_preflight(tmp_path / "preflight")
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "full_test", command, archive)
    base = [
        sys.executable,
        str(PROTOCOL),
        "--workspace-root",
        str(tmp_path),
        "--preflight",
        str(preflight),
        "close",
        str(task),
        "--evidence",
        str(evidence),
        "--json",
    ]
    processes = [
        subprocess.Popen(
            [*base, "--approval-ref", "approval:user:2026-07-20"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ),
        subprocess.Popen(
            [
                *base,
                "--reviewer",
                "reviewer-b",
                "--review-ref",
                "review:task-1:final",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ),
    ]
    results = [process.communicate(timeout=30) for process in processes]
    reports = [json.loads(stdout) for stdout, _ in results]
    final = cli(
        preflight, tmp_path, "close", task, "--evidence", evidence, "--json"
    )

    assert sorted(report["result"]["status"] for report in reports) == [
        "BLOCKED",
        "COMPLETE",
    ]
    assert json.loads(final.stdout)["result"]["status"] == "COMPLETE"


def test_writer_lock_is_released_after_holder_process_is_killed(tmp_path):
    protocol = load_protocol()
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    preflight = make_preflight(tmp_path / "preflight")
    lock_path = protocol.registry_path_for(repo).with_name("writer.lock")
    holder_code = (
        "import fcntl,os,sys,time; "
        "p=sys.argv[1]; os.makedirs(os.path.dirname(p),exist_ok=True); "
        "f=open(p,'a+b'); fcntl.flock(f,fcntl.LOCK_EX); "
        "print('locked',flush=True); time.sleep(30)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(lock_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert holder.stdout.readline().strip() == "locked"
    blocked = cli(
        preflight,
        tmp_path,
        "--lock-timeout",
        "0.05",
        "start",
        task,
        "--json",
    )
    holder.kill()
    holder.wait(timeout=10)
    recovered = start(preflight, tmp_path, task)

    assert blocked.returncode == 3
    assert "writer lock timed out" in blocked.stdout
    assert recovered.returncode == 0


def test_close_is_idempotent(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    evidence = tmp_path / "evidence.json"
    preflight = make_preflight(tmp_path / "preflight")
    command = [sys.executable, "-c", "print('ok')"]
    start(preflight, tmp_path, task)
    run_acceptance(preflight, tmp_path, task, evidence, "focused_test", command)

    first = cli(preflight, tmp_path, "close", task, "--evidence", evidence, "--json")
    state_path = task.parent / ".taskctl" / "task-1.state.json"
    first_state = state_path.read_bytes()
    second = cli(preflight, tmp_path, "close", task, "--evidence", evidence, "--json")

    assert first.stdout == second.stdout
    assert first_state == state_path.read_bytes()


def test_installed_taskctl_works_from_temporary_runtime_view(tmp_path):
    repo = init_repo(tmp_path / "repo")
    task = write_task(tmp_path, repo)
    preflight = make_preflight(tmp_path / "preflight")
    installed = tmp_path / "installed"
    assert run(
        str(INSTALL_LINKS),
        "--target-root",
        str(installed),
        "--state-file",
        str(tmp_path / "install-state.json"),
        "--allow-linked-worktree",
        check=False,
    ).returncode == 0

    result = run(
        str(installed / "scripts" / "taskctl"),
        "--workspace-root",
        str(tmp_path),
        "--preflight",
        str(preflight),
        "start",
        str(task),
        "--json",
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["result"]["status"] == "READY"
    assert (installed / "templates" / "task.md").is_file()
