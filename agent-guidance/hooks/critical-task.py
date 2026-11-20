#!/usr/bin/env python3
"""Track consequential work and check proposed turn closure."""

import argparse
import fcntl
import json
import os
import re
import stat
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


TERMINAL = ("verified", "handed-off", "blocked", "stopped")
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
EXPLICIT_STAKES = re.compile(r"不容许失败|不允许失败|不可失败|不能失败|\bmust not fail\b|\bfailure is not an option\b", re.I)
PLACEHOLDERS = {"none", "n/a", "na", "todo", "tbd", "ok", "pass", "success", "yes", "done", "无", "通过", "待定", "已完成", "已验收"}
HINT = "用户明确标记了高风险。先核对实际目标和授权。关键行动任务按全局规约登记，限定的只读或复盘按原范围验收。"
ACTIVE_HINT = "本会话有尚未收尾的关键任务。先核对登记的目标、授权与证据，再判断本轮是否属于该任务。"
STOP_REASON = "本会话登记的关键任务仍未收尾。先核对实际结果或交接证据。若有可继续的已授权工作就继续。若阻塞、停止或已交接，依据真实证据登记状态。"
RETRY_WARNING = "关键任务仍未收尾。请在当前回复如实写明进度、缺少的证据和下一步责任。"
STATE_WARNING = "无法核对关键任务记录。当前状态未经核验。"


def required_text(value, field):
    if not isinstance(value, str) or not value.strip() or value.strip().casefold() in PLACEHOLDERS:
        raise ValueError(f"{field} 需要具体内容。")
    return value.strip()


def parse_time(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} 需要带时区的 ISO 8601 时间。")
    try:
        timestamp = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise ValueError(f"{field} 需要带时区的 ISO 8601 时间。") from None
    if timestamp.utcoffset() is None:
        raise ValueError(f"{field} 需要带时区的 ISO 8601 时间。")
    return timestamp


def acceptance_times(record):
    deadline = parse_time(record["deadline"], "--deadline") if record.get("deadline") is not None else None
    recover_by = parse_time(record["recover_by"], "--recover-by") if record.get("recover_by") is not None else None
    if deadline is not None and recover_by is not None and recover_by > deadline:
        raise ValueError("--recover-by 必须早于或等于 --deadline。")
    return deadline, recover_by


def check_handoff(record, at):
    for field in ("owner", "ack", "drill"):
        required_text(record.get(field), f"--{field}")
    check = parse_time(record.get("next_check"), "--next-check")
    if check <= at:
        raise ValueError("--next-check 必须晚于当前时间。")
    deadline, recover_by = acceptance_times(record)
    if deadline is not None and (recover_by is None or recover_by >= deadline):
        raise ValueError("有硬时限的交接需要早于截止的 --recover-by。")
    if recover_by is not None and check > recover_by:
        raise ValueError("--next-check 必须早于或等于最迟补救时点。")


def check_record(record, session):
    if (not isinstance(record, dict) or record.get("version") != 1 or record.get("session_id") != session or
            record.get("status") not in ("active", *TERMINAL)):
        raise ValueError("关键任务记录无效或不属于此会话。")
    for field in ("outcome", "scope", "acceptance"):
        required_text(record.get(field), field)
    started = parse_time(record.get("started_at"), "started_at")
    deadline, _ = acceptance_times(record)
    if record["status"] in TERMINAL:
        required_text(record.get("evidence"), "--evidence")
        closed = parse_time(record.get("closed_at"), "closed_at")
        if closed < started:
            raise ValueError("关键任务结束时间早于开始时间。")
        if record["status"] == "verified":
            occurred_at = record.get("occurred_at")
            if deadline is not None and occurred_at is None:
                raise ValueError("有硬时限的验收需要记录实际结果的 --occurred-at。")
            if occurred_at is not None:
                actual = parse_time(occurred_at, "--occurred-at")
                if actual > closed or (deadline is not None and actual > deadline):
                    raise ValueError("结果发生时间超过验收时间或截止时间。")
        if record["status"] == "handed-off":
            check_handoff(record, closed)
    return record


def ensure_private(descriptor, directory=False):
    metadata = os.fstat(descriptor)
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077 or not expected_type(metadata.st_mode):
        raise ValueError("关键任务状态路径不是当前用户的私有目录或文件。")


@contextmanager
def state_directory(root, create=False):
    if create:
        root.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        ensure_private(descriptor, directory=True)
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def session_lock(directory, session):
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(f"{session}.lock", flags, 0o600, dir_fd=directory)
    try:
        ensure_private(descriptor)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("本会话的关键任务记录正在更新。") from None
        yield
    finally:
        os.close(descriptor)


def read_record(directory, session):
    try:
        descriptor = os.open(f"{session}.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, encoding="utf-8") as stream:
        ensure_private(stream.fileno())
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("关键任务记录超过本地读取上限。")
    return check_record(json.loads(raw), session)


def load_record(root, session):
    try:
        with state_directory(root) as directory:
            return read_record(directory, session)
    except FileNotFoundError:
        return None


def write_record(directory, record, session):
    filename = f".{uuid4().hex}.tmp"
    raw = json.dumps(check_record(record, session), ensure_ascii=False) + "\n"
    if len(raw) > 65536:
        raise ValueError("关键任务记录超过本地读取上限。")
    descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(raw)
        os.replace(filename, f"{session}.json", src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            os.unlink(filename, dir_fd=directory)
        except FileNotFoundError:
            pass


def hook_check(payload, root):
    if not isinstance(payload, dict):
        return None
    session = payload.get("session_id")
    event = payload.get("hook_event_name")
    if event not in ("UserPromptSubmit", "Stop") or not isinstance(session, str) or not SESSION_ID.fullmatch(session):
        return None
    try:
        record = load_record(root, session.lower())
    except (OSError, ValueError):
        return {"systemMessage": STATE_WARNING}

    active = record is not None and record["status"] == "active"
    if event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        hint = ACTIVE_HINT if active else HINT if isinstance(prompt, str) and EXPLICIT_STAKES.search(prompt) else None
        if hint:
            return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": hint}}
    elif active:
        if payload.get("stop_hook_active") is True:
            return {"systemMessage": RETRY_WARNING}
        return {"decision": "block", "reason": STOP_REASON}
    return None


def parser():
    arguments = argparse.ArgumentParser(description="记录关键任务并核对收尾条件。")
    commands = arguments.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    for field in ("outcome", "scope", "acceptance"):
        start.add_argument(f"--{field}", required=True)
    start.add_argument("--deadline")
    start.add_argument("--recover-by")
    revise = commands.add_parser("revise")
    revise.add_argument("--reason", required=True)
    for field in ("outcome", "scope", "acceptance", "deadline", "recover-by"):
        revise.add_argument(f"--{field}")
    commands.add_parser("status")
    close = commands.add_parser("close")
    close.add_argument("--as", dest="disposition", choices=TERMINAL, required=True)
    close.add_argument("--evidence", required=True)
    close.add_argument("--occurred-at")
    for field in ("owner", "next-check", "ack", "drill"):
        close.add_argument(f"--{field}")
    commands.add_parser("hook")
    return arguments


def main(argv=None, *, state_root=None):
    args = parser().parse_args(argv)
    root = Path(state_root) if state_root is not None else Path("/tmp").resolve() / f"codex-critical-task-{os.getuid()}"
    if args.command == "hook":
        try:
            payload = json.loads(sys.stdin.read(1048577))
        except (OSError, ValueError):
            return 0
        decision = hook_check(payload, root)
        if decision is not None:
            print(json.dumps(decision, ensure_ascii=False))
        return 0

    session = os.environ.get("CODEX_SESSION_ID", "").lower()
    if not SESSION_ID.fullmatch(session):
        print("缺少有效的 CODEX_SESSION_ID。请在当前 Codex 会话内运行。", file=sys.stderr)
        return 2

    try:
        if args.command == "status":
            record = load_record(root, session) or {"status": "none"}
        else:
            with state_directory(root, create=args.command == "start") as directory, session_lock(directory, session):
                record = read_record(directory, session)
                now = datetime.now(timezone.utc).isoformat()
                if args.command == "start":
                    if record is not None and record["status"] == "active":
                        raise ValueError("本会话已有关键任务在执行。先核对并保留该任务的状态。")
                    record = {"version": 1, "session_id": session, "status": "active", "started_at": now,
                              "outcome": required_text(args.outcome, "--outcome"),
                              "scope": required_text(args.scope, "--scope"),
                              "acceptance": required_text(args.acceptance, "--acceptance"),
                              "deadline": args.deadline, "recover_by": args.recover_by}
                else:
                    if record is None or record["status"] != "active":
                        raise ValueError("本会话没有待收尾的关键任务。")
                    if args.command == "revise":
                        changes = {field: getattr(args, field) for field in ("outcome", "scope", "acceptance", "deadline", "recover_by")
                                   if getattr(args, field) is not None}
                        if not changes:
                            raise ValueError("请指定需要修订的字段。")
                        record.update(changes, revised_at=now, revision_reason=required_text(args.reason, "--reason"))
                    else:
                        record.update(status=args.disposition, closed_at=now, evidence=required_text(args.evidence, "--evidence"))
                        if args.occurred_at is not None:
                            if args.disposition != "verified":
                                raise ValueError("--occurred-at 仅适用于 --as verified。")
                            record["occurred_at"] = args.occurred_at
                        if args.disposition == "handed-off":
                            record.update(owner=args.owner, next_check=args.next_check, ack=args.ack, drill=args.drill)
                        elif any(getattr(args, name) is not None for name in ("owner", "next_check", "ack", "drill")):
                            raise ValueError("交接参数仅适用于 --as handed-off。")
                write_record(directory, record, session)
        print(json.dumps(record, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as error:
        print(f"关键任务记录失败。{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
