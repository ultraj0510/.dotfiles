"""Save and load analysis.json + run manifest."""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


def save_analysis(data_dir, ticker, run_id, analysis, run_manifest):
    run_dir = Path(data_dir) / ticker / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(run_dir / "analysis.json", json.dumps(analysis, ensure_ascii=False, indent=2, allow_nan=False))
    _atomic_write(run_dir / "run-manifest.json", json.dumps(run_manifest, ensure_ascii=False, indent=2, allow_nan=False))
    latest_path = Path(data_dir) / ticker / "latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(latest_path, json.dumps({
        "latest_run_id": run_id,
        "latest_status": analysis.get("status"),
        "latest_rating": analysis.get("rating", {}).get("final"),
        "updated_at": datetime.now().astimezone().isoformat(),
    }, ensure_ascii=False, indent=2))


def load_previous_analysis(data_dir, ticker):
    latest_path = Path(data_dir) / ticker / "latest.json"
    try:
        latest = json.loads(latest_path.read_text())
        run_id = latest.get("latest_run_id")
        if not run_id:
            return None
        analysis_path = Path(data_dir) / ticker / "runs" / run_id / "analysis.json"
        return json.loads(analysis_path.read_text())
    except Exception:
        return None


def _atomic_write(path, data):
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent, suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)
