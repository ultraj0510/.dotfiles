#!/usr/bin/env python3
"""Deterministic local task risk and completion-evidence protocol."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = 1
LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3}
EXIT_CODES = {"COMPLETE": 0, "READY": 0, "PARTIAL": 1, "BLOCKED": 2, "ERROR": 3}
L1_TRIGGERS = {"local_change", "reversible"}
L2_TRIGGERS = {
    "external_side_effect",
    "schema_or_contract_change",
    "cross_module_change",
    "public_behavior_change",
    "persisted_data_change",
    "dependency_change",
}
L3_TRIGGERS = {
    "money",
    "production",
    "security",
    "credentials",
    "destructive_migration",
    "irreversible_external_action",
}
ALL_TRIGGERS = L1_TRIGGERS | L2_TRIGGERS | L3_TRIGGERS
EVIDENCE_KINDS = {
    "focused_test",
    "regression_test",
    "full_test",
    "lint",
    "diff_check",
    "smoke",
    "review",
    "preflight",
}
PREFLIGHT_EXIT_CODES = {"PASS": 0, "WARN": 1, "BLOCKED": 2, "ERROR": 3}
PLACEHOLDERS = {"", "none", "null", "todo", "tbd", "placeholder", "n/a"}


class TaskSchemaError(ValueError):
    pass


class ManagedStateError(ValueError):
    pass


class EvidenceError(ValueError):
    pass


class PreflightInterfaceError(RuntimeError):
    pass


class CliError(RuntimeError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError(message)


def canonical_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_json(value):
    return sha256_bytes(canonical_bytes(value))


def file_sha256(path):
    return sha256_bytes(Path(path).read_bytes())


def managed_digest(state):
    return sha256_json({key: value for key, value in state.items() if key != "integrity_sha256"})


def atomic_write_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(path, value):
    atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode() + b"\n")


def load_managed_state(path):
    path = Path(path)
    try:
        state = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ManagedStateError(str(exc)) from exc
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        raise ManagedStateError("managed state schema is invalid")
    if state.get("integrity_sha256") != managed_digest(state):
        raise ManagedStateError("managed state integrity check failed")
    return state


def write_managed_state(path, state):
    value = dict(state)
    value["integrity_sha256"] = managed_digest(value)
    atomic_write_json(path, value)
    return value


def max_level(*levels):
    try:
        return max(levels, key=lambda level: LEVEL_ORDER[level])
    except (KeyError, ValueError) as exc:
        raise TaskSchemaError("risk level must be L1, L2, or L3") from exc


def classify_risk(triggers, minimum_level):
    if not isinstance(triggers, (list, tuple, set)) or not triggers:
        raise TaskSchemaError("at least one valid risk trigger is required")
    unique = sorted(set(triggers))
    unknown = sorted(set(unique) - ALL_TRIGGERS)
    if unknown:
        raise TaskSchemaError(f"unknown risk triggers: {unknown}")
    derived = "L3" if set(unique) & L3_TRIGGERS else "L2" if set(unique) & L2_TRIGGERS else "L1"
    level = max_level(derived, minimum_level)
    return {
        "level": level,
        "derived_level": derived,
        "minimum_level": minimum_level,
        "matched_triggers": unique,
        "raised_by_minimum": level != derived,
    }


def parse_front_matter(path):
    text = Path(path).read_text()
    lines = text.splitlines()
    if not lines or lines[0] != "+++":
        raise TaskSchemaError("task must begin with TOML front matter")
    try:
        end = lines[1:].index("+++") + 1
    except ValueError as exc:
        raise TaskSchemaError("task front matter is not closed") from exc
    try:
        return tomllib.loads("\n".join(lines[1:end]))
    except tomllib.TOMLDecodeError as exc:
        raise TaskSchemaError(str(exc)) from exc


def normalize_allowed_path(value):
    if not isinstance(value, str) or not value:
        raise TaskSchemaError("allowed paths must be non-empty strings")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise TaskSchemaError(f"allowed path escapes repository: {value}")
    normalized = path.as_posix()
    return normalized if normalized.endswith("/") else f"{normalized}/"


def git_text(repo, *args, allowed=(0,)):
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=False
    )
    if result.returncode not in allowed:
        raise TaskSchemaError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


def resolve_repository(value, workspace_root):
    if not isinstance(value, str) or not value:
        raise TaskSchemaError("repo must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        path = Path(workspace_root) / path
    path = path.resolve()
    if not path.is_dir() or not (path / ".git").exists():
        raise TaskSchemaError("repo must be an existing Git work tree root")
    top = Path(git_text(path, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if top != path:
        raise TaskSchemaError("repo path is not the Git work tree root")
    return path


def load_task(path, workspace_root):
    data = parse_front_matter(path)
    required = {
        "schema_version",
        "id",
        "repo",
        "allowed_paths",
        "minimum_level",
        "implementer",
        "acceptance",
        "risk",
    }
    missing = sorted(required - set(data))
    if missing:
        raise TaskSchemaError(f"missing task fields: {missing}")
    if data["schema_version"] != SCHEMA_VERSION:
        raise TaskSchemaError("unsupported task schema_version")
    task_id = data["id"]
    if not isinstance(task_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id) is None:
        raise TaskSchemaError("task id must use only letters, digits, dot, underscore, and hyphen")
    implementer = data["implementer"]
    if not isinstance(implementer, str) or not implementer.strip():
        raise TaskSchemaError("implementer is required")
    risk = data["risk"]
    if not isinstance(risk, dict) or set(risk) != ALL_TRIGGERS:
        missing_risk = sorted(ALL_TRIGGERS - set(risk or {})) if isinstance(risk, dict) else sorted(ALL_TRIGGERS)
        unknown = sorted(set(risk or {}) - ALL_TRIGGERS) if isinstance(risk, dict) else []
        raise TaskSchemaError(f"risk trigger schema mismatch; missing={missing_risk} unknown={unknown}")
    if not all(isinstance(value, bool) for value in risk.values()):
        raise TaskSchemaError("risk trigger values must be booleans")
    triggers = sorted(name for name, enabled in risk.items() if enabled)
    risk_result = classify_risk(triggers, data["minimum_level"])
    if not isinstance(data["allowed_paths"], list):
        raise TaskSchemaError("allowed_paths must be an array")
    allowed_paths = [normalize_allowed_path(value) for value in data["allowed_paths"]]
    if not allowed_paths or len(allowed_paths) != len(set(allowed_paths)):
        raise TaskSchemaError("allowed_paths must be non-empty and unique")
    acceptance = data["acceptance"]
    if not isinstance(acceptance, list) or not acceptance:
        raise TaskSchemaError("at least one acceptance item is required")
    normalized_acceptance = []
    identifiers = []
    for item in acceptance:
        if not isinstance(item, dict) or set(item) != {"id", "description", "command"}:
            raise TaskSchemaError("acceptance items require id, description, and command")
        identifier = item["id"]
        command = item["command"]
        if not isinstance(identifier, str) or not identifier:
            raise TaskSchemaError("acceptance id is required")
        if not isinstance(item["description"], str) or not item["description"]:
            raise TaskSchemaError("acceptance description is required")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise TaskSchemaError("acceptance command must be a non-empty argv array")
        identifiers.append(identifier)
        normalized_acceptance.append(
            {"id": identifier, "description": item["description"], "command": command}
        )
    if len(identifiers) != len(set(identifiers)):
        raise TaskSchemaError("acceptance ids must be unique")
    repo = resolve_repository(data["repo"], workspace_root)
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "id": task_id,
        "repo": str(repo),
        "allowed_paths": sorted(allowed_paths),
        "minimum_level": data["minimum_level"],
        "implementer": implementer.strip(),
        "acceptance": normalized_acceptance,
        "risk": {name: risk[name] for name in sorted(risk)},
    }
    return {
        **normalized,
        "path": str(Path(path).resolve()),
        "triggers": triggers,
        "risk_result": risk_result,
        "definition_digest": sha256_json(normalized),
        "acceptance_digest": sha256_json(normalized_acceptance),
    }


def state_path_for(task_path, task_id):
    return Path(task_path).resolve().parent / ".taskctl" / f"{task_id}.state.json"


def registry_path_for(repository):
    repository = Path(repository).resolve()
    git_path = Path(
        git_text(repository, "rev-parse", "--git-path", "taskctl/registry.json")
        .stdout.strip()
    )
    return (git_path if git_path.is_absolute() else repository / git_path).resolve()


def load_registry(path):
    registry = load_managed_state(path)
    tasks = registry.get("tasks")
    if not isinstance(tasks, dict) or not all(
        isinstance(repository_tasks, dict) for repository_tasks in tasks.values()
    ):
        raise ManagedStateError("task registry schema is invalid")
    return registry


def registry_entry(task, risk):
    return {
        "repository_identity": task["repo"],
        "historical_triggers": risk["matched_triggers"],
        "risk_floor": risk["level"],
    }


def is_allowed(path, allowed_paths):
    normalized = PurePosixPath(path).as_posix()
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in allowed_paths
    )


def git_bytes(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise EvidenceError(result.stderr.decode(errors="replace").strip() or "git command failed")
    return result.stdout


def workspace_snapshot(repo, allowed_paths):
    repo = Path(repo).resolve()
    branch_result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "<detached>"
    head = git_bytes(repo, "rev-parse", "HEAD").decode().strip()
    staged_diff = git_bytes(repo, "diff", "--cached", "--binary")
    unstaged_diff = git_bytes(repo, "diff", "--binary")
    staged_paths = [path for path in git_bytes(repo, "diff", "--cached", "--name-only", "-z").decode().split("\0") if path]
    unstaged_paths = [path for path in git_bytes(repo, "diff", "--name-only", "-z").decode().split("\0") if path]
    untracked_paths = [path for path in git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0") if path]
    relevant_untracked = []
    for relative in sorted(untracked_paths):
        if not is_allowed(relative, allowed_paths):
            continue
        path = repo / relative
        relevant_untracked.append(
            {
                "path": relative,
                "sha256": sha256_bytes(path.read_bytes()) if path.is_file() else sha256_bytes(os.readlink(path).encode()),
            }
        )
    facts = {
        "repository_identity": str(repo),
        "branch": branch,
        "head": head,
        "staged_diff_sha256": sha256_bytes(staged_diff),
        "unstaged_diff_sha256": sha256_bytes(unstaged_diff),
        "relevant_untracked": relevant_untracked,
        "changed_paths": sorted(set(staged_paths + unstaged_paths + untracked_paths)),
    }
    facts["fingerprint"] = sha256_json({key: value for key, value in facts.items() if key not in {"fingerprint", "changed_paths"}})
    return facts


def preflight_summary(report):
    return {
        "schema_version": report["schema_version"],
        "status": report["status"],
        "finding_codes": [finding["code"] for finding in report["findings"]],
    }


def invoke_preflight(executable, repo):
    try:
        result = subprocess.run(
            [str(executable), "--json", "--repo", str(repo)],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise PreflightInterfaceError(str(exc)) from exc
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightInterfaceError("preflight did not return valid JSON") from exc
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA_VERSION:
        raise PreflightInterfaceError("preflight schema_version is incompatible")
    status = report.get("status")
    if status not in PREFLIGHT_EXIT_CODES or not isinstance(report.get("findings"), list):
        raise PreflightInterfaceError("preflight report structure is invalid")
    if result.returncode != PREFLIGHT_EXIT_CODES[status]:
        raise PreflightInterfaceError("preflight exit code and JSON status disagree")
    if status == "ERROR":
        raise PreflightInterfaceError("preflight reported ERROR")
    return report


def effective_risk(task, state=None):
    triggers = set(task["triggers"])
    minimum = task["minimum_level"]
    if state:
        triggers.update(state["historical_triggers"])
        minimum = max_level(minimum, state["risk_floor"])
    return classify_risk(sorted(triggers), minimum)


def initial_state(task):
    risk = task["risk_result"]
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task["id"],
        "repository_identity": task["repo"],
        "implementer": task["implementer"],
        "historical_triggers": risk["matched_triggers"],
        "risk_floor": risk["level"],
        "evidence_path": None,
        "evidence_sha256": None,
        "gates": {"approval": None, "review": None},
        "initial_workspace": None,
        "initial_preflight": None,
        "last_result": None,
    }


def update_state_risk(state, task):
    risk = effective_risk(task, state)
    state = dict(state)
    state["historical_triggers"] = risk["matched_triggers"]
    state["risk_floor"] = risk["level"]
    return state, risk


def valid_reference(value):
    return isinstance(value, str) and value.strip().lower() not in PLACEHOLDERS and len(value.strip()) >= 8


def new_evidence(task):
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task["id"],
        "repository_identity": task["repo"],
        "commands": [],
        "artifacts": [],
    }


def load_evidence(path, state, task_id):
    path = Path(path).resolve()
    if not path.is_file():
        raise EvidenceError("evidence file is missing")
    if state.get("evidence_path") != str(path):
        raise EvidenceError("evidence path does not match managed state")
    if state.get("evidence_sha256") != file_sha256(path):
        raise EvidenceError("evidence integrity check failed")
    try:
        evidence = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise EvidenceError("evidence JSON is invalid") from exc
    if not isinstance(evidence, dict) or evidence.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceError("evidence schema is invalid")
    if evidence.get("task_id") != task_id:
        raise EvidenceError("evidence belongs to another task")
    return evidence


def acceptance_map(task):
    return {item["id"]: item for item in task["acceptance"]}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def command_exit_code(returncode, execution_error):
    if execution_error:
        return 127
    if returncode < 0:
        return 128 + abs(returncode)
    return returncode


def command_start(args, context):
    task = load_task(args.task, context.workspace_root)
    state_path = state_path_for(args.task, task["id"])
    registry_path = registry_path_for(task["repo"])
    try:
        registry = (
            load_registry(registry_path)
            if registry_path.exists()
            else {"schema_version": SCHEMA_VERSION, "tasks": {}}
        )
    except ManagedStateError as exc:
        return error_output("start", task["id"], str(exc))
    repository_tasks = registry["tasks"].setdefault(task["repo"], {})
    registered = repository_tasks.get(task["id"])
    if registered is not None and not state_path.exists():
        risk = effective_risk(task, registered)
        report = {
            "schema_version": SCHEMA_VERSION,
            "command": "start",
            "task_id": task["id"],
            "risk": risk,
            "result": {
                "status": "BLOCKED",
                "reasons": ["MANAGED_STATE_MISSING"],
            },
        }
        return report, 2
    if registered is None and state_path.exists():
        return error_output("start", task["id"], "task registry entry is missing")
    try:
        state = load_managed_state(state_path) if state_path.exists() else initial_state(task)
    except ManagedStateError as exc:
        return error_output("start", task["id"], str(exc))
    if state["task_id"] != task["id"]:
        return error_output("start", task["id"], "managed state task id mismatch")
    state, risk = update_state_risk(state, task)
    try:
        preflight = invoke_preflight(context.preflight, task["repo"])
    except PreflightInterfaceError as exc:
        return error_output("start", task["id"], str(exc), risk)
    reasons = []
    if state["repository_identity"] != task["repo"]:
        reasons.append("TASK_REPOSITORY_CHANGED")
    if preflight["status"] == "BLOCKED":
        reasons.append("PREFLIGHT_BLOCKED")
    status = "BLOCKED" if reasons else "READY"
    if state["initial_workspace"] is None:
        state["initial_workspace"] = workspace_snapshot(
            task["repo"], task["allowed_paths"]
        )
        state["initial_preflight"] = preflight_summary(preflight)
    state["last_result"] = {"command": "start", "status": status, "reasons": reasons}
    repository_tasks[task["id"]] = registry_entry(task, risk)
    write_managed_state(registry_path, registry)
    write_managed_state(state_path, state)
    report = {
        "schema_version": SCHEMA_VERSION,
        "command": "start",
        "task_id": task["id"],
        "risk": risk,
        "preflight": preflight_summary(preflight),
        "result": {"status": status, "reasons": reasons},
    }
    return report, EXIT_CODES[status]


def command_classify(args, context):
    task = load_task(args.task, context.workspace_root)
    report = {
        "schema_version": SCHEMA_VERSION,
        "command": "classify",
        "task_id": task["id"],
        "risk": task["risk_result"],
        "result": {"status": "READY", "reasons": []},
    }
    return report, 0


def command_run(args, context):
    task = load_task(args.task, context.workspace_root)
    state_path = state_path_for(args.task, task["id"])
    try:
        state = load_managed_state(state_path)
    except ManagedStateError as exc:
        return error_output("run", task["id"], str(exc))
    state, risk = update_state_risk(state, task)
    if state["repository_identity"] != task["repo"]:
        report = {
            "schema_version": SCHEMA_VERSION,
            "command": "run",
            "task_id": task["id"],
            "risk": risk,
            "result": {"status": "BLOCKED", "reasons": ["TASK_REPOSITORY_CHANGED"]},
        }
        return report, 2
    requested = sorted(set(args.acceptance))
    definitions = acceptance_map(task)
    if not requested or any(identifier not in definitions for identifier in requested):
        raise CliError("--acceptance must reference declared acceptance ids")
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise CliError("run requires a command after --")
    if any(definitions[identifier]["command"] != argv for identifier in requested):
        raise CliError("run command does not match the task acceptance definition")
    if args.kind not in EVIDENCE_KINDS:
        raise CliError("unsupported evidence kind")
    if risk["level"] == "L3" and (args.archive_dir is None or not Path(args.archive_dir).is_dir()):
        raise CliError("L3 run requires an existing --archive-dir")
    try:
        preflight = invoke_preflight(context.preflight, task["repo"])
    except PreflightInterfaceError as exc:
        return error_output("run", task["id"], str(exc), risk)
    evidence_path = Path(args.evidence).resolve()
    if state.get("evidence_path"):
        evidence = load_evidence(evidence_path, state, task["id"])
    else:
        evidence = new_evidence(task)
    started_at = utc_now()
    execution_error = None
    try:
        completed = subprocess.run(argv, cwd=task["repo"], capture_output=True, check=False)
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except OSError as exc:
        returncode = None
        stdout = b""
        stderr = str(exc).encode()
        execution_error = str(exc)
    finished_at = utc_now()
    snapshot = workspace_snapshot(task["repo"], task["allowed_paths"])
    index = len(evidence["commands"])
    archive = None
    if args.archive_dir is not None:
        archive_root = Path(args.archive_dir).resolve() / task["id"]
        stdout_path = archive_root / f"command-{index:03d}.stdout"
        stderr_path = archive_root / f"command-{index:03d}.stderr"
        atomic_write_bytes(stdout_path, stdout)
        atomic_write_bytes(stderr_path, stderr)
        archive = {
            "stdout_path": str(stdout_path),
            "stdout_sha256": sha256_bytes(stdout),
            "stderr_path": str(stderr_path),
            "stderr_sha256": sha256_bytes(stderr),
        }
        evidence["artifacts"].append(archive)
    record = {
        "id": f"command:{index}",
        "task_id": task["id"],
        "kind": args.kind,
        "acceptance_ids": requested,
        "argv": argv,
        "cwd": task["repo"],
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": returncode,
        "execution_error": execution_error,
        "stdout_sha256": sha256_bytes(stdout),
        "stderr_sha256": sha256_bytes(stderr),
        "task_definition_digest": task["definition_digest"],
        "acceptance_digest": task["acceptance_digest"],
        "workspace": snapshot,
        "preflight": preflight_summary(preflight),
        "archive": archive,
    }
    evidence["commands"].append(record)
    atomic_write_json(evidence_path, evidence)
    state["evidence_path"] = str(evidence_path)
    state["evidence_sha256"] = file_sha256(evidence_path)
    state["last_result"] = {
        "command": "run",
        "status": "PASS" if returncode == 0 and not execution_error else "FAIL",
        "command_id": record["id"],
    }
    write_managed_state(state_path, state)
    status = "PASS" if returncode == 0 and not execution_error else "FAIL"
    report = {
        "schema_version": SCHEMA_VERSION,
        "command": "run",
        "task_id": task["id"],
        "risk": risk,
        "preflight": preflight_summary(preflight),
        "command_result": {"id": record["id"], "status": status, "exit_code": returncode},
        "result": {"status": status, "reasons": [] if status == "PASS" else ["COMMAND_FAILED"]},
    }
    return report, command_exit_code(returncode if returncode is not None else 0, execution_error)


def archive_valid(record):
    archive = record.get("archive")
    if not isinstance(archive, dict):
        return False
    for stream in ("stdout", "stderr"):
        path = archive.get(f"{stream}_path")
        digest = archive.get(f"{stream}_sha256")
        if not path or not Path(path).is_file() or file_sha256(path) != digest:
            return False
    return True


def valid_command_records(evidence, task, snapshot):
    valid = []
    invalid_reasons = set()
    definitions = acceptance_map(task)
    for record in evidence.get("commands", []):
        if record.get("task_id") != task["id"] or evidence.get("task_id") != task["id"]:
            invalid_reasons.add("EVIDENCE_TASK_MISMATCH")
            continue
        if evidence.get("repository_identity") != task["repo"] or record.get("workspace", {}).get("repository_identity") != task["repo"]:
            invalid_reasons.add("EVIDENCE_REPOSITORY_MISMATCH")
            continue
        if record.get("task_definition_digest") != task["definition_digest"] or record.get("acceptance_digest") != task["acceptance_digest"]:
            invalid_reasons.add("EVIDENCE_DEFINITION_MISMATCH")
            continue
        if record.get("workspace", {}).get("fingerprint") != snapshot["fingerprint"]:
            invalid_reasons.add("EVIDENCE_STALE")
            continue
        identifiers = record.get("acceptance_ids", [])
        if not identifiers or any(identifier not in definitions for identifier in identifiers):
            invalid_reasons.add("EVIDENCE_ACCEPTANCE_MISMATCH")
            continue
        if any(definitions[identifier]["command"] != record.get("argv") for identifier in identifiers):
            invalid_reasons.add("EVIDENCE_COMMAND_MISMATCH")
            continue
        if record.get("preflight", {}).get("schema_version") != SCHEMA_VERSION:
            invalid_reasons.add("EVIDENCE_PREFLIGHT_SCHEMA_MISMATCH")
            continue
        valid.append(record)
    return valid, sorted(invalid_reasons)


def command_close(args, context):
    task = load_task(args.task, context.workspace_root)
    state_path = state_path_for(args.task, task["id"])
    try:
        state = load_managed_state(state_path)
    except ManagedStateError:
        report = close_report(task, task["risk_result"], None, "BLOCKED", ["MANAGED_STATE_MISSING_OR_INVALID"], [], None, {})
        return report, 2
    state, risk = update_state_risk(state, task)
    reasons = []
    if state["repository_identity"] != task["repo"]:
        reasons.append("TASK_REPOSITORY_CHANGED")
    try:
        preflight = invoke_preflight(context.preflight, task["repo"])
    except PreflightInterfaceError as exc:
        return error_output("close", task["id"], str(exc), risk)
    if preflight["status"] == "BLOCKED":
        reasons.append("PREFLIGHT_BLOCKED")
    snapshot = workspace_snapshot(task["repo"], task["allowed_paths"])
    outside = [path for path in snapshot["changed_paths"] if not is_allowed(path, task["allowed_paths"])]
    if outside:
        reasons.append("CHANGED_PATH_OUTSIDE_SCOPE")
    evidence = None
    valid_records = []
    invalid = []
    try:
        evidence = load_evidence(args.evidence, state, task["id"])
        valid_records, invalid = valid_command_records(evidence, task, snapshot)
    except EvidenceError:
        reasons.append("EVIDENCE_MISSING_OR_INVALID")
    definitions = acceptance_map(task)
    acceptance_results = []
    missing_acceptance = False
    failed_acceptance = False
    for identifier in definitions:
        records = [record for record in valid_records if identifier in record["acceptance_ids"]]
        if any(record.get("exit_code") == 0 and not record.get("execution_error") for record in records):
            status = "PASS"
        elif records:
            status = "FAIL"
            failed_acceptance = True
        else:
            status = "MISSING"
            missing_acceptance = True
        acceptance_results.append({"id": identifier, "status": status})
    if failed_acceptance:
        reasons.append("ACCEPTANCE_FAILED")
    if missing_acceptance:
        reasons.append("ACCEPTANCE_INCOMPLETE")
    if failed_acceptance or missing_acceptance:
        reasons.extend(invalid)
    successful = [record for record in valid_records if record.get("exit_code") == 0 and not record.get("execution_error")]
    if risk["level"] == "L2" and not any(record["kind"] in {"regression_test", "full_test"} for record in successful):
        reasons.append("REGRESSION_EVIDENCE_MISSING")
    gates = dict(state["gates"])
    if args.approval_ref is not None and valid_reference(args.approval_ref):
        gates["approval"] = {"task_id": task["id"], "reference": args.approval_ref.strip()}
    if args.reviewer is not None or args.review_ref is not None:
        if (
            valid_reference(args.reviewer)
            and valid_reference(args.review_ref)
            and args.reviewer.strip() != state["implementer"]
        ):
            gates["review"] = {
                "task_id": task["id"],
                "reviewer": args.reviewer.strip(),
                "reference": args.review_ref.strip(),
                "workspace_fingerprint": snapshot["fingerprint"],
            }
    if risk["level"] == "L3":
        if not gates.get("approval") or gates["approval"].get("task_id") != task["id"]:
            reasons.append("L3_APPROVAL_MISSING")
        review = gates.get("review")
        if (
            not review
            or review.get("task_id") != task["id"]
            or review.get("reviewer") == state["implementer"]
            or review.get("workspace_fingerprint") != snapshot["fingerprint"]
        ):
            reasons.append("L3_REVIEW_MISSING")
        if not successful or not all(archive_valid(record) for record in successful):
            reasons.append("L3_ARCHIVE_MISSING")
        if not any(record["kind"] == "full_test" for record in successful):
            reasons.append("L3_FULL_TEST_MISSING")
    reasons = sorted(set(reasons))
    blocking = {
        reason
        for reason in reasons
        if reason
        not in {"ACCEPTANCE_INCOMPLETE", "REGRESSION_EVIDENCE_MISSING"}
    }
    if blocking:
        status = "BLOCKED"
    elif reasons:
        status = "PARTIAL"
    else:
        status = "COMPLETE"
    state["gates"] = gates
    state["last_result"] = {"command": "close", "status": status, "reasons": reasons}
    write_managed_state(state_path, state)
    report = close_report(
        task,
        risk,
        preflight_summary(preflight),
        status,
        reasons,
        acceptance_results,
        args.evidence,
        gates,
    )
    return report, EXIT_CODES[status]


def close_report(task, risk, preflight, status, reasons, acceptance, evidence_path, gates):
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "close",
        "task_id": task["id"],
        "risk": risk,
        "preflight": preflight,
        "acceptance": acceptance,
        "evidence": {"path": str(Path(evidence_path).resolve()) if evidence_path else None},
        "gates": gates,
        "result": {"status": status, "reasons": reasons},
    }


def error_output(command, task_id, message, risk=None):
    report = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "task_id": task_id,
        "risk": risk,
        "result": {"status": "ERROR", "reasons": [message]},
    }
    return report, 3


def render_human(report):
    result = report["result"]
    lines = [
        f"Result: {result['status']}",
        f"Risk: {(report.get('risk') or {}).get('level')}",
        f"Task: {report.get('task_id')}",
        "Reasons:",
    ]
    lines.extend(f"- {reason}" for reason in result.get("reasons", []))
    if not result.get("reasons"):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def parse_args(argv):
    command_argv = []
    parseable = list(argv)
    if "run" in parseable and "--" in parseable:
        separator = parseable.index("--")
        command_argv = parseable[separator + 1 :]
        parseable = parseable[:separator]
    source_root = Path(__file__).resolve().parents[2]
    parser = Parser()
    parser.add_argument("--workspace-root", type=Path, default=Path("/Users/fujie/code"))
    parser.add_argument("--preflight", type=Path, default=source_root / "scripts" / "preflight")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    classify = subparsers.add_parser("classify")
    classify.add_argument("task", type=Path)
    classify.add_argument("--json", action="store_true")
    start = subparsers.add_parser("start")
    start.add_argument("task", type=Path)
    start.add_argument("--json", action="store_true")
    execute = subparsers.add_parser("run")
    execute.add_argument("task", type=Path)
    execute.add_argument("--evidence", type=Path, required=True)
    execute.add_argument("--kind", required=True)
    execute.add_argument("--acceptance", action="append", required=True)
    execute.add_argument("--archive-dir", type=Path)
    execute.add_argument("--json", action="store_true")
    execute.set_defaults(argv=[])
    close = subparsers.add_parser("close")
    close.add_argument("task", type=Path)
    close.add_argument("--evidence", type=Path, required=True)
    close.add_argument("--approval-ref")
    close.add_argument("--reviewer")
    close.add_argument("--review-ref")
    close.add_argument("--json", action="store_true")
    args = parser.parse_args(parseable)
    if args.operation == "run":
        args.argv = command_argv
    return args


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    wants_json = "--json" in argv
    try:
        args = parse_args(argv)
        handler = {
            "classify": command_classify,
            "start": command_start,
            "run": command_run,
            "close": command_close,
        }[args.operation]
        report, code = handler(args, args)
        wants_json = args.json
    except (CliError, TaskSchemaError, EvidenceError) as exc:
        report, code = error_output("unknown", None, str(exc))
    except Exception as exc:
        report, code = error_output("internal", None, f"internal taskctl error: {exc}")
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if wants_json else render_human(report)
    sys.stdout.write(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
