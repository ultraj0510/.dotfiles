"""PID + expiry-based lock manager for same-ticker exclusion."""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
LOCK_TIMEOUT_MINUTES = 60


@dataclass
class LockResult:
    acquired: bool
    existing_run_id: str | None = None


def acquire_lock(ticker, run_id, data_dir, force_stale=False):
    lock_path = Path(data_dir) / ticker / "analysis.lock"
    if lock_path.exists():
        if force_stale and is_stale_lock(lock_path):
            lock_path.unlink(missing_ok=True)
        else:
            try:
                existing = json.loads(lock_path.read_text())
                return LockResult(acquired=False, existing_run_id=existing.get("run_id"))
            except Exception:
                return LockResult(acquired=False, existing_run_id="unknown")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    expires = datetime.now(JST) + timedelta(minutes=LOCK_TIMEOUT_MINUTES)
    lock_data = {
        "run_id": run_id, "pid": os.getpid(),
        "started_at": datetime.now(JST).isoformat(),
        "expires_at": expires.isoformat(),
    }
    lock_path.write_text(json.dumps(lock_data))
    return LockResult(acquired=True)


def release_lock(ticker, data_dir):
    lock_path = Path(data_dir) / ticker / "analysis.lock"
    lock_path.unlink(missing_ok=True)


def is_stale_lock(lock_path):
    try:
        data = json.loads(lock_path.read_text())
        expires = datetime.fromisoformat(data["expires_at"])
        if datetime.now(JST) > expires:
            return True
        pid = data.get("pid")
        if pid:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
        return False
    except Exception:
        return True
