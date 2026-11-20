import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path(__file__).with_name("critical-task.py")
SESSION = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
RUN_CLI = """
import runpy, sys
program, directory, *arguments = sys.argv[1:]
sys.exit(runpy.run_path(program)["main"](arguments, state_root=directory))
"""


class TaskGuardTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "state"

    def cli(self, *arguments, payload=None, session=SESSION):
        return subprocess.run(
            [sys.executable, "-c", RUN_CLI, str(SCRIPT), str(self.root), *arguments],
            input=json.dumps(payload, ensure_ascii=False) if payload is not None else "",
            text=True, capture_output=True, timeout=5,
            env={**os.environ, "CODEX_SESSION_ID": session, "CODEX_THREAD_ID": OTHER},
        )

    def start(self, *extra):
        return self.cli("start", "--outcome", "目标商品出现在购物车", "--scope", "只加购一件",
                        "--acceptance", "官网购物车的商品 ID 和数量", *extra)

    def hook(self, event="Stop", session=SESSION, **extra):
        return self.cli("hook", payload={"hook_event_name": event, "session_id": session, **extra})

    def status(self):
        return json.loads(self.cli("status").stdout)

    def test_no_record_never_creates_state(self):
        self.assertEqual(self.status(), {"status": "none"})
        self.assertEqual(self.hook().stdout, "")
        self.assertEqual(self.hook("UserPromptSubmit", prompt="只读核对当前任务是否仍在运行").stdout, "")
        self.assertFalse(self.root.exists())

    def test_explicit_high_stakes_only_adds_context(self):
        result = self.hook("UserPromptSubmit", prompt="这次不容许失败。原文包含 TEST-NO-OUTPUT。")
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("原范围", output["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("TEST-NO-OUTPUT", result.stdout)
        self.assertFalse(self.root.exists())

    def test_active_session_blocks_once_and_does_not_leak_state(self):
        self.assertEqual(self.start().returncode, 0)
        self.assertEqual(self.status()["session_id"], SESSION)
        stop = self.hook(stop_hook_active=False)
        self.assertEqual(stop.returncode, 0)
        self.assertEqual(json.loads(stop.stdout)["decision"], "block")
        self.assertNotIn("只加购一件", stop.stdout)
        retry = json.loads(self.hook(stop_hook_active=True).stdout)
        self.assertEqual(list(retry), ["systemMessage"])
        self.assertEqual(self.hook(session=OTHER).stdout, "")
        prompt = json.loads(self.hook("UserPromptSubmit", prompt="现在跑了吗").stdout)
        self.assertIn("授权", prompt["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.root.stat().st_mode & 0o077, 0)
        self.assertEqual((self.root / f"{SESSION}.json").stat().st_mode & 0o077, 0)

    def test_invalid_session_and_event_are_ignored(self):
        self.assertEqual(self.start().returncode, 0)
        self.assertEqual(self.hook(session="../../invalid").stdout, "")
        self.assertEqual(self.hook("SubagentStop").stdout, "")
        self.assertEqual(self.cli("status", session="not-a-uuid").returncode, 2)

    def test_active_goal_is_not_overwritten_by_followup(self):
        self.assertEqual(self.start().returncode, 0)
        original = self.status()
        result = self.cli("start", "--outcome", "只看进程号", "--scope", "只读", "--acceptance", "PID")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.status(), original)

    def test_rejects_unknown_timezone_and_inverted_cutoffs(self):
        self.assertEqual(self.start("--deadline", "2050-11-20T12:00:00").returncode, 2)
        self.assertEqual(self.start("--deadline", "2050-11-20T12:00:00+09:00", "--recover-by", "2050-11-20T12:01:00+09:00").returncode, 2)
        self.assertEqual(self.status(), {"status": "none"})

    def test_revise_keeps_original_scope_and_record_open(self):
        self.assertEqual(self.start().returncode, 0)
        before = self.status()
        result = self.cli("revise", "--reason", "用户确认截止时间", "--deadline", "2050-11-20T12:00:00+09:00")
        self.assertEqual(result.returncode, 0)
        after = self.status()
        for field in ("started_at", "outcome", "scope", "acceptance", "status"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after["deadline"], "2050-11-20T12:00:00+09:00")
        self.assertEqual(json.loads(self.hook().stdout)["decision"], "block")

    def test_evidence_preserves_active_until_valid_terminal_state(self):
        self.assertEqual(self.start().returncode, 0)
        for value in (" ", "已完成", "TODO"):
            self.assertEqual(self.cli("close", "--as", "verified", "--evidence", value).returncode, 2)
        self.assertEqual(self.status()["status"], "active")
        self.assertEqual(self.cli("close", "--as", "verified", "--evidence", "官网购物车回读商品 425755 数量 1").returncode, 0)
        self.assertEqual(self.hook().stdout, "")
        self.assertEqual(self.status()["status"], "verified")

    def test_handoff_requires_acceptance_before_recovery_cutoff(self):
        now = datetime.now(timezone.utc)
        cutoff = (now + timedelta(minutes=8)).isoformat()
        deadline = (now + timedelta(minutes=10)).isoformat()
        self.assertEqual(self.start("--deadline", deadline, "--recover-by", cutoff).returncode, 0)
        close = ("close", "--as", "handed-off", "--evidence", "现场监看日志 11:49 等待中",
                 "--owner", "已授权的现场值守者")
        soon = (now + timedelta(minutes=1)).isoformat()
        self.assertEqual(self.cli(*close, "--next-check", soon).returncode, 2)
        observed = ("--ack", "现场值守者确认收到故障通知，回执 17", "--drill", "隔离演练记录 004 显示退出与接手完成")
        self.assertEqual(self.cli(*close, "--next-check", (now + timedelta(minutes=9)).isoformat(), *observed).returncode, 2)
        self.assertEqual(self.cli(*close, "--next-check", (now - timedelta(seconds=5)).isoformat(), *observed).returncode, 2)
        self.assertEqual(self.status()["status"], "active")
        self.assertEqual(self.cli(*close, "--next-check", soon, *observed).returncode, 0)
        self.assertEqual(self.status()["status"], "handed-off")
        self.assertEqual(self.hook().stdout, "")

    def test_deadline_alone_cannot_validate_timed_handoff(self):
        now = datetime.now(timezone.utc)
        deadline = (now + timedelta(minutes=10)).isoformat()
        recovery = (now + timedelta(minutes=8)).isoformat()
        check = (now + timedelta(minutes=1)).isoformat()
        self.assertEqual(self.start("--deadline", deadline).returncode, 0)
        close = ("close", "--as", "handed-off", "--evidence", "当前后台状态已回读", "--owner", "现场值守者",
                 "--next-check", check, "--ack", "值守者确认接手", "--drill", "退出演练记录")
        self.assertEqual(self.cli(*close).returncode, 2)
        self.assertEqual(self.cli("revise", "--reason", "核对恢复所需时间", "--recover-by", deadline).returncode, 0)
        self.assertEqual(self.cli(*close).returncode, 2)
        self.assertEqual(self.cli("revise", "--reason", "留出安全恢复时间", "--recover-by", recovery).returncode, 0)
        self.assertEqual(self.cli(*close).returncode, 0)

    def test_timed_completion_uses_when_result_occurred_not_when_read_back(self):
        now = datetime.now(timezone.utc)
        deadline = (now - timedelta(seconds=20)).isoformat()
        self.assertEqual(self.start("--deadline", deadline).returncode, 0)
        close = ("close", "--as", "verified", "--evidence", "目标系统记录显示完成时点")
        self.assertEqual(self.cli(*close).returncode, 2)
        self.assertEqual(self.cli(*close, "--occurred-at", (now - timedelta(seconds=5)).isoformat()).returncode, 2)
        self.assertEqual(self.status()["status"], "active")
        self.assertEqual(self.cli(*close, "--occurred-at", deadline).returncode, 0)
        self.assertEqual(self.hook().stdout, "")

    def test_reservation_replay_distinguishes_installation_from_completion(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(self.start("--deadline", (now - timedelta(minutes=1)).isoformat(),
                                    "--recover-by", (now - timedelta(minutes=5)).isoformat()).returncode, 0)
        self.assertEqual(json.loads(self.hook().stdout)["decision"], "block")
        attempted = self.cli("close", "--as", "handed-off", "--evidence", "已部署预约进程",
                             "--owner", "现场值守者", "--next-check", (now + timedelta(minutes=1)).isoformat(),
                             "--ack", "现场值守者确认接手", "--drill", "过去一次退出演练记录")
        self.assertEqual(attempted.returncode, 2)
        result = self.cli("close", "--as", "blocked", "--evidence",
                          "11:50 进程退出，12:20 回读两件加购次数均为 0，用户确认售罄")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.hook().stdout, "")
        self.assertEqual(self.status()["status"], "blocked")

    def test_user_stops_task_explicitly(self):
        self.assertEqual(self.start().returncode, 0)
        result = self.cli("close", "--as", "stopped", "--evidence", "用户要求停止后续执行并只读核对")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.hook().stdout, "")

    def test_corrupt_record_reports_unverified_state_without_leaking(self):
        self.assertEqual(self.start().returncode, 0)
        path = self.root / f"{SESSION}.json"
        path.write_text("BROKEN-PRIVATE-CONTENT", encoding="utf-8")
        result = self.hook()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(list(json.loads(result.stdout)), ["systemMessage"])
        self.assertNotIn("BROKEN-PRIVATE-CONTENT", result.stdout)
        self.assertEqual(self.cli("status").returncode, 2)
        self.assertEqual(self.start().returncode, 2)

    def test_state_symlink_is_rejected(self):
        self.assertEqual(self.start().returncode, 0)
        path = self.root / f"{SESSION}.json"
        unrelated = self.root / "unrelated"
        path.rename(unrelated)
        path.symlink_to(unrelated)
        self.assertEqual(list(json.loads(self.hook().stdout)), ["systemMessage"])
        self.assertEqual(self.cli("close", "--as", "verified", "--evidence", "官方购物车确认数量 1").returncode, 2)
        self.assertTrue(path.is_symlink())


if __name__ == "__main__":
    unittest.main()
