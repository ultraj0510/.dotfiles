#!/usr/bin/env python3
"""Weekday monitor — checks registered tickers for major IR events."""
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from watchlist import load_watchlist, update_last_checked, update_last_event
from event_detector import detect_events, Event

JST = ZoneInfo("Asia/Tokyo")
DEFAULT_DATA_DIR = Path("/Users/fujie/code/runtime/stock-company-analysis")

SKILL_PATHS = {
    "stock-info-fetch": "/Users/fujie/.dotfiles/claude/skills/stock-info-fetch/scripts/fetch_stock_info",
    "stock-ir-fetch": "/Users/fujie/.dotfiles/claude/skills/stock-ir-fetch/scripts/fetch_stock_ir",
    "stock-company-analyze": "/Users/fujie/.dotfiles/claude/skills/stock-company-analyze/scripts/stock_company_analyze",
    "stock-company-report": "/Users/fujie/.dotfiles/claude/skills/stock-company-report/scripts/stock_company_report",
}


@dataclass
class TickerReport:
    ticker: str
    events: list = field(default_factory=list)
    reanalysis_run_id: str | None = None
    reanalysis_failed: bool = False
    error: str | None = None


@dataclass
class MonitorReport:
    checked_at: str
    tickers_checked: int
    events_found: int
    reanalyses_triggered: int
    reanalyses_failed: int
    results: list = field(default_factory=list)


def _run_skill(skill_name, args, timeout=300):
    exe = SKILL_PATHS[skill_name]
    proc = None
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, shell=False)
        parsed = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        parsed = None
    rc = proc.returncode if proc else -1
    return type("R", (), {"parsed": parsed, "exit_code": rc})()


# --- Event Ledger ---

def _ledger_path(ticker, data_dir):
    return Path(data_dir) / ticker / "event-ledger.json"


def _load_ledger(ticker, data_dir):
    path = _ledger_path(ticker, data_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("events", [])
    except (json.JSONDecodeError, KeyError):
        return []


def _append_ledger(ticker, data_dir, events):
    path = _ledger_path(ticker, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_ledger(ticker, data_dir)
    for e in events:
        existing.append({
            "event_id": f"{e.detected_at[:10]}-{e.document_id}",
            "ticker": ticker, "event_type": e.event_type,
            "detected_at": e.detected_at, "document_id": e.document_id,
            "title": e.title, "reanalysis_run_id": None, "reanalysis_status": "pending",
        })
    path.write_text(json.dumps({"schema_version": "1.0", "events": existing}, ensure_ascii=False, indent=2))


def _update_ledger_reanalysis(ticker, data_dir, document_id, run_id, status):
    path = _ledger_path(ticker, data_dir)
    if not path.exists():
        return
    data = json.loads(path.read_text())
    for e in data.get("events", []):
        if e["document_id"] == document_id:
            e["reanalysis_run_id"] = run_id
            e["reanalysis_status"] = status
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _notify_failure(ticker, event_type, error):
    notification = {
        "type": "monitor_reanalysis_failed", "ticker": ticker,
        "event_type": event_type, "error": error[:500],
        "timestamp": datetime.now(JST).isoformat(), "action_required": "manual_review",
    }
    log_path = DEFAULT_DATA_DIR / "monitor-failures.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(notification, ensure_ascii=False) + "\n")
    return notification


# --- Core ---

def check_ticker(ticker, data_dir, skill_runner=_run_skill):
    report = TickerReport(ticker=ticker)

    # SNAPSHOT previous manifest BEFORE fetch (critical: fetch overwrites it)
    prev_path = Path(data_dir) / ticker / "raw" / "stock-ir-fetch" / "manifest.json"
    prev_manifest = None
    if prev_path.exists():
        try:
            prev_manifest = json.loads(prev_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Load event ledger for dedup
    ledger = _load_ledger(ticker, data_dir)
    seen = {e["document_id"] for e in ledger}

    # Fetch (this UPDATES manifest.json)
    try:
        ir_result = skill_runner("stock-ir-fetch", [ticker, "--data-dir", str(data_dir)])
    except Exception as e:
        report.error = f"IR fetch failed: {e}"
        return report

    if ir_result.parsed is None:
        report.error = "IR fetch returned invalid JSON"
        return report

    # Detect + dedup
    events = detect_events(prev_manifest, ir_result.parsed, None)
    new = [e for e in events if e.document_id not in seen]
    for e in new:
        e.ticker = ticker
    report.events = new

    if new:
        _append_ledger(ticker, data_dir, new)
    return report


def expire_rating(ticker, data_dir, reason):
    latest_path = Path(data_dir) / ticker / "latest.json"
    if not latest_path.exists():
        return
    try:
        data = json.loads(latest_path.read_text())
    except Exception:
        return
    data["latest_status"] = "expired"
    data["expired_at"] = datetime.now(JST).isoformat()
    data["expired_reason"] = reason
    latest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def trigger_reanalysis(ticker, data_dir):
    try:
        proc = subprocess.run(
            [SKILL_PATHS["stock-company-analyze"], ticker, "--data-dir", str(data_dir)],
            capture_output=True, text=True, timeout=3600, shell=False,
        )
        if proc.returncode != 0:
            return None, f"analyze failed: {proc.stderr[:200]}"
        analysis = json.loads(proc.stdout)
        run_id = analysis.get("run_id")
        subprocess.run(
            [SKILL_PATHS["stock-company-report"], ticker, "--run-id", run_id, "--data-dir", str(data_dir)],
            capture_output=True, text=True, timeout=120, shell=False,
        )
        return run_id, None
    except subprocess.TimeoutExpired:
        return None, "Reanalysis timeout"
    except Exception as e:
        return None, str(e)


def monitor(data_dir=DEFAULT_DATA_DIR, auto_reanalyze=False):
    now = datetime.now(JST)

    # Weekday gate
    if now.weekday() >= 5:
        return MonitorReport(now.isoformat(), 0, 0, 0, 0)

    wl = load_watchlist(data_dir)
    if not wl:
        return MonitorReport(now.isoformat(), 0, 0, 0, 0)

    results = []
    total_events = triggered = failed = 0

    for entry in wl:
        ticker = entry["ticker"]
        report = check_ticker(ticker, data_dir)
        results.append(report)
        update_last_checked(ticker, data_dir, now.isoformat())

        if report.events:
            total_events += len(report.events)
            reason = "; ".join(f"{e.event_type}: {e.title}" for e in report.events)
            doc_ids = [e.document_id for e in report.events]
            expire_rating(ticker, data_dir, reason)
            update_last_event(ticker, data_dir, now.isoformat(), doc_ids)

            if auto_reanalyze:
                run_id, err = trigger_reanalysis(ticker, data_dir)
                if run_id:
                    report.reanalysis_run_id = run_id
                    triggered += 1
                    for e in report.events:
                        _update_ledger_reanalysis(ticker, data_dir, e.document_id, run_id, "completed")
                else:
                    report.reanalysis_failed = True
                    report.error = err
                    failed += 1
                    for e in report.events:
                        _update_ledger_reanalysis(ticker, data_dir, e.document_id, None, "failed")
                        _notify_failure(ticker, e.event_type, err)

    return MonitorReport(now.isoformat(), len(wl), total_events, triggered, failed, results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="stock-company-monitor")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run")
    run_p.add_argument("--auto-reanalyze", action="store_true")
    run_p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)

    add_p = sub.add_parser("add")
    add_p.add_argument("ticker")
    add_p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)

    rm_p = sub.add_parser("remove")
    rm_p.add_argument("ticker")
    rm_p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)

    list_p = sub.add_parser("list")
    list_p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)

    args = parser.parse_args()

    if args.command == "add":
        from watchlist import add_to_watchlist
        add_to_watchlist(args.ticker, args.data_dir)
        print(f"ADDED {args.ticker}")
    elif args.command == "remove":
        from watchlist import remove_from_watchlist
        remove_from_watchlist(args.ticker, args.data_dir)
        print(f"REMOVED {args.ticker}")
    elif args.command == "list":
        wl = load_watchlist(args.data_dir)
        if not wl:
            print("(empty)")
        for t in wl:
            lc = t.get('last_checked_at', 'never') or 'never'
            print(f"{t['ticker']} — registered {t['registered_at'][:10]}, last checked {lc[:10]}")
    elif args.command == "run":
        report = monitor(args.data_dir, args.auto_reanalyze)
        json.dump({
            "checked_at": report.checked_at,
            "tickers_checked": report.tickers_checked,
            "events_found": report.events_found,
            "reanalyses_triggered": report.reanalyses_triggered,
            "reanalyses_failed": report.reanalyses_failed,
            "results": [{"ticker": r.ticker, "events": [{"event_type": e.event_type, "title": e.title} for e in r.events],
                         "reanalysis_run_id": r.reanalysis_run_id, "reanalysis_failed": r.reanalysis_failed, "error": r.error} for r in report.results],
        }, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        parser.print_help()
